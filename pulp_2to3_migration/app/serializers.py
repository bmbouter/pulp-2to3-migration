import json

from gettext import gettext as _
from django.urls import reverse
from jsonschema import Draft7Validator
from pymongo.errors import OperationFailure
from rest_framework import serializers

from pulp_2to3_migration.app.plugin import PLUGIN_MIGRATORS
from pulp_2to3_migration.pulp2 import connection

from pulpcore.app.models import RepositoryVersion
from pulpcore.plugin.serializers import NestedRelatedField
from pulpcore.app.settings import INSTALLED_PULP_PLUGINS
from pulpcore.app.util import get_view_name_for_model
from pulpcore.plugin.serializers import (
    ModelSerializer,
    DetailRelatedField,
    IdentityField,
)

from pulp_2to3_migration.app.json_schema import SCHEMA
from .models import (
    MigrationPlan,
    Pulp2Content,
    Pulp2Distributor,
    Pulp2Importer,
    Pulp2Repository,
)


def get_pulp_href(obj):
    """
    Get pulp_href for a given model object.
    """
    if obj:
        return reverse(get_view_name_for_model(obj.cast(), "detail"), args=[obj.pk])


class MigrationPlanSerializer(ModelSerializer):
    """Serializer for migration plan model."""
    pulp_href = IdentityField(
        view_name='migration-plans-detail'
    )

    plan = serializers.JSONField(
        help_text=_('Migration Plan in JSON format'),
        required=True,
    )

    class Meta:
        fields = ModelSerializer.Meta.fields + ('plan', )
        model = MigrationPlan

    def validate(self, data):
        """
        Validate that the Serializer contains valid data.

        Validates JSON structure of migration_plan.
        Checks pulp2 and pulp3 plugins are installed.
        """
        schema = json.loads(SCHEMA)
        validator = Draft7Validator(schema)
        if isinstance(data['plan'], str):
            loaded_plan = json.loads(data['plan'])
        elif isinstance(data['plan'], dict):
            loaded_plan = data['plan']
        else:
            raise serializers.ValidationError(
                _("Must provide a (JSON-encoded) string or dict for 'plan', not list")
            )
        err = []
        for error in sorted(validator.iter_errors(loaded_plan), key=str):
            err.append(error.message)
        if err:
            raise serializers.ValidationError(
                _("Provided Migration Plan format is invalid:'{}'".format(err))
            )
        plugins_to_migrate = set()
        for plugin_type in loaded_plan['plugins']:
            plugins_to_migrate.add(plugin_type['type'])
        if len(loaded_plan['plugins']) != len(plugins_to_migrate):
            raise serializers.ValidationError(
                _("Provided Migration Plan contains same plugin type specified more that once.")
            )
        # MongoDB connection initialization
        connection.initialize()
        db = connection.get_database()
        for plugin in plugins_to_migrate:
            plugin_migrator = PLUGIN_MIGRATORS.get(plugin)
            if not plugin_migrator:
                raise serializers.ValidationError(
                    _("Migration of {} plugin is not supported.".format(plugin))
                )
            if plugin_migrator.pulp3_plugin not in INSTALLED_PULP_PLUGINS:
                raise serializers.ValidationError(
                    _("Plugin {} is not installed in pulp3.".format(plugin))
                )
            try:
                db.command("collstats", plugin_migrator.pulp2_collection)
            except OperationFailure:
                raise serializers.ValidationError(
                    _("Plugin {} is not installed in pulp2.".format(plugin))
                )
        data['plan'] = loaded_plan
        return data


class MigrationPlanRunSerializer(serializers.Serializer):
    """
    A serializer for running a migration plan.
    """
    validate = serializers.BooleanField(
        help_text=_('If ``True``, migration cannot happen without successful validation '
                    'of the Migration Plan'),
        required=False,
        default=False,
        write_only=True
    )
    dry_run = serializers.BooleanField(
        help_text=_('If ``True``, performs validation of a Migration Plan only, no migration is '
                    'run.'),
        required=False,
        default=False,
        write_only=True
    )


class Pulp2ContentSerializer(ModelSerializer):
    """
    A serializer for the Pulp2Content model
    """
    pulp_href = IdentityField(
        view_name='migration-plans-detail'
    )
    pulp2_id = serializers.CharField(max_length=255)
    pulp2_content_type_id = serializers.CharField(max_length=255)
    pulp2_last_updated = serializers.IntegerField()
    pulp2_storage_path = serializers.CharField()
    downloaded = serializers.BooleanField(default=False)
    pulp3_content = DetailRelatedField(
        required=False, allow_null=True, queryset=Pulp2Content.objects.all()
    )

    class Meta:
        fields = ModelSerializer.Meta.fields + ('pulp2_id', 'pulp2_content_type_id',
                                                'pulp2_last_updated', 'pulp2_storage_path',
                                                'downloaded', 'pulp3_content')
        model = Pulp2Content


class Pulp2RepositoriesSerializer(ModelSerializer):
    """
    A serializer for the Pulp2Repositories
    """
    pulp_href = IdentityField(
        view_name='pulp2repositories-detail'
    )
    pulp2_object_id = serializers.CharField(max_length=255)
    pulp2_repo_id = serializers.CharField()
    is_migrated = serializers.BooleanField(default=False)

    pulp3_repository_version = NestedRelatedField(
        view_name='versions-detail',
        lookup_field='number',
        parent_lookup_kwargs={'repository_pk': 'repository__pk'},
        queryset=RepositoryVersion.objects.all(),
        required=False,
    )

    pulp3_remote_href = serializers.SerializerMethodField(read_only=True)
    pulp3_publisher_href = serializers.SerializerMethodField(read_only=True)
    pulp3_publication_href = serializers.SerializerMethodField(read_only=True)
    pulp3_distribution_hrefs = serializers.SerializerMethodField(read_only=True)

    def get_pulp3_remote_href(self, obj):
        """
        Get pulp3_remote_href from Pulp2Importer
        """
        importer = Pulp2Importer.objects.filter(pulp2_repository=obj).first()
        return get_pulp_href(importer.pulp3_remote)

    def get_pulp3_publisher_href(self, obj):
        """
        Get pulp3_publisher_href from Pulp2Distributor
        """
        distributors = getattr(self, "_distributors", None)
        if not distributors:
            self._distributors = Pulp2Distributor.objects.filter(pulp2_repository=obj).all()
            distributors = self._distributors

        return [get_pulp_href(d.pulp3_publisher) for d in distributors if d.pulp3_publisher]

    def get_pulp3_publication_href(self, obj):
        """
        Get pulp3_publication_href from Pulp2Distributor
        """
        distributors = getattr(self, "_distributors", None)
        if not distributors:
            self._distributors = Pulp2Distributor.objects.filter(pulp2_repository=obj).all()
            distributors = self._distributors

        return [get_pulp_href(d.pulp3_publication) for d in distributors if d.pulp3_publication]

    def get_pulp3_distribution_hrefs(self, obj):
        """
        Get pulp3_distribution_hrefs from Pulp2Distributor
        """
        distributors = getattr(self, "_distributors", None)
        if not distributors:
            self._distributors = Pulp2Distributor.objects.filter(pulp2_repository=obj).all()
            distributors = self._distributors

        return [get_pulp_href(d.pulp3_distribution) for d in distributors if d.pulp3_distribution]

    class Meta:
        fields = ModelSerializer.Meta.fields + (
            "pulp2_object_id",
            "pulp2_repo_id",
            "is_migrated",
            "pulp3_repository_version",
            "pulp3_remote_href",
            "pulp3_publisher_href",
            "pulp3_publication_href",
            "pulp3_distribution_hrefs",
        )
        model = Pulp2Repository
