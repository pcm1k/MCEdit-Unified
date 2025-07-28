import unittest
from pymclevel import fromFile
from pymclevel.entity import Entity, getTileEntityDefs
from pymclevel.id_definitions import get_defs_ids, PLATFORM_ALPHA, VERSION_LATEST
from templevel import TempLevel

__author__ = 'Rio'


class TestEntities(unittest.TestCase):
    def testCommandBlockOffset(self):
        tileEntityDefs = getTileEntityDefs(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST))
        commandTag = tileEntityDefs.Create("minecraft:command_block")
        commandTag["Command"].value = originalCommand = "/tp @p 0 10 0"
        offsetCommand = "/tp @p 100 210 300"
        importCommand = "/tp @p 200 410 600"
        copyOffset = (100, 200, 300)

        offsetTag = tileEntityDefs.copyWithOffset(commandTag, copyOffset, toSchematic=None, moveCommandPos=False)
        assert "MCEditOffsetCommand" not in offsetTag
        assert offsetTag["Command"].value == originalCommand

        offsetTag = tileEntityDefs.copyWithOffset(commandTag, copyOffset, toSchematic=None, moveCommandPos=True)
        assert "MCEditOffsetCommand" not in offsetTag
        assert offsetTag["Command"].value == offsetCommand

        offsetTag = tileEntityDefs.copyWithOffset(commandTag, copyOffset, toSchematic=True, moveCommandPos=True)
        assert offsetTag["MCEditOffsetCommand"].value == offsetCommand
        assert offsetTag["Command"].value == originalCommand

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=False, moveCommandPos=False)
        assert "MCEditOffsetCommand" not in importTag
        assert importTag["Command"].value == originalCommand

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=False, moveCommandPos=True)
        assert "MCEditOffsetCommand" not in importTag
        assert importTag["Command"].value == importCommand

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=None, moveCommandPos=False)
        assert "MCEditOffsetCommand" not in importTag
        assert importTag["Command"].value == originalCommand

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=None, moveCommandPos=True)
        assert "MCEditOffsetCommand" not in importTag
        assert importTag["Command"].value == importCommand

    def testSpawnerOffset(self):
        tileEntityDefs = getTileEntityDefs(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST))
        spawnerTag = tileEntityDefs.Create("minecraft:mob_spawner")
        originalPos = [0, 10, 0]
        Entity.setpos(spawnerTag["SpawnData"], originalPos)
        offsetPos = [100, 210, 300]
        importPos = [200, 410, 600]
        copyOffset = (100, 200, 300)

        offsetTag = tileEntityDefs.copyWithOffset(spawnerTag, copyOffset, toSchematic=None, moveSpawnerPos=False)
        spawnData = offsetTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == originalPos

        offsetTag = tileEntityDefs.copyWithOffset(spawnerTag, copyOffset, toSchematic=None, moveSpawnerPos=True)
        spawnData = offsetTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == offsetPos

        offsetTag = tileEntityDefs.copyWithOffset(spawnerTag, copyOffset, toSchematic=True, moveSpawnerPos=True)
        spawnData = offsetTag["SpawnData"]
        assert [p.value for p in spawnData["MCEditOffsetPos"]] == offsetPos
        assert Entity.pos(spawnData) == originalPos

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=False, moveSpawnerPos=False)
        spawnData = importTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == originalPos

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=False, moveSpawnerPos=True)
        spawnData = importTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == importPos

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=None, moveSpawnerPos=False)
        spawnData = importTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == originalPos

        importTag = tileEntityDefs.copyWithOffset(offsetTag, copyOffset, toSchematic=None, moveSpawnerPos=True)
        spawnData = importTag["SpawnData"]
        assert "MCEditOffsetPos" not in spawnData
        assert Entity.pos(spawnData) == importPos

    def testTileEntityBaseNbt(self):
        tileEntityDefs = getTileEntityDefs(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST))
        furnaceTag = tileEntityDefs.Create("minecraft:furnace")
        assert "BurnTime" in furnaceTag
