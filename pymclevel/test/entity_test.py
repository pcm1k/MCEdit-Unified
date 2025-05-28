import unittest
from pymclevel import fromFile
from pymclevel.entity import getTileEntityDefs
from pymclevel.id_definitions import get_defs_ids, PLATFORM_ALPHA, VERSION_LATEST
from templevel import TempLevel

__author__ = 'Rio'


class TestEntities(unittest.TestCase):
    def test_command_block(self):
        level = TempLevel("AnvilWorld").level

        cmdblock = fromFile("testfiles/Commandblock.schematic")

        point = level.bounds.origin + [p / 2 for p in level.bounds.size]
        level.copyBlocksFrom(cmdblock, cmdblock.bounds, point)

        te = level.tileEntityAt(*point)
        command = te['Command'].value
        words = command.split(' ')
        x, y, z = words[2:5]
        assert x == str(point[0])
        assert y == str(point[1] + 10)
        assert z == str(point[2])

    def testTileEntityBaseNbt(self):
        tileEntityDefs = getTileEntityDefs(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST))
        furnaceTag = tileEntityDefs.Create("minecraft:furnace")
        assert "BurnTime" in furnaceTag
