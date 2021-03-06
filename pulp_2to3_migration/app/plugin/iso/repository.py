from pulp_2to3_migration.app.plugin.api import Pulp2to3Importer

from pulp_file.app.models import FileRemote


class IsoImporter(Pulp2to3Importer):
    """
    Interface to migrate Pulp 2 ISO importer
    """
    @classmethod
    async def migrate_to_pulp3(cls, pulp2importer):
        """
        Migrate importer to Pulp 3.

        Args:
            pulp2importer(Pulp2Importer): Pre-migrated pulp2 importer to migrate

        Return:
            remote(FileRemote): FileRemote in Pulp3
            created(bool): True if Remote has just been created; False if Remote is an existing one
        """
        pulp2_config = pulp2importer.pulp2_config
        base_config = cls.parse_base_config(pulp2importer, pulp2_config)
        return FileRemote.objects.update_or_create(**base_config)
