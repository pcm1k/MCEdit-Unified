import anvil_test
from templevel import TempLevel

__author__ = 'Rio'


# pcm1k TODO - reimplement MCRegion format levels so this doesn't fail
class TestMCR(anvil_test.TestAnvilLevel):
    def setUp(self):
        self.indevLevel = TempLevel("hell.mclevel")
        self.anvilLevel = TempLevel("PyTestWorld")
