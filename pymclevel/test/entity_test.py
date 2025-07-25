import unittest
from pymclevel import fromFile
from pymclevel.entity import getTileEntityDefs
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

    def testTileEntityBaseNbt(self):
        tileEntityDefs = getTileEntityDefs(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST))
        furnaceTag = tileEntityDefs.Create("minecraft:furnace")
        assert "BurnTime" in furnaceTag
