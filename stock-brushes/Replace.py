from pymclevel.materials import Block, data_limit
from editortools.brush import createBrushMask, createTileEntities
from pymclevel import block_fill

displayName = 'Replace'
mainBlock = 'Block To Replace With'
secondaryBlock = 'Block'
wildcardBlocks = ['Block']


def createInputs(self):
    self.inputs = (
    {'Hollow': False},
    {'Noise': 100},
    {'W': (3, 1, 4096), 'H': (3, 1, 4096), 'L': (3, 1, 4096)},
    {'Block': materials.blockWithID(1, 0)},
    {'Block To Replace With': materials.blockWithID(1, 0)},
    {'Swap': tool.swap},
    {'Minimum Spacing': 1}
    )


def applyToChunkSlices(self, op, chunk, slices, brushBox, brushBoxThisChunk):
    brushMask = createBrushMask(op.tool.getBrushSize(), op.options['Style'], brushBox.origin, brushBoxThisChunk, op.options['Noise'], op.options['Hollow'])

    blocks = chunk.Blocks[slices]
    data = chunk.Data[slices]

    if op.options['Block'].wildcard:
        print "Wildcard replace"
        blocksToReplace = []
        for i in xrange(data_limit):
            blocksToReplace.append(op.editor.level.materials.blockWithID(op.options['Block'].ID, i))
    else:
        blocksToReplace = [op.options['Block']]

    replaceFunc = block_fill.blockReplaceFunc(blocksToReplace)
    replaceMask = replaceFunc(blocks, data)
    brushMask &= replaceMask

    chunk.Blocks[slices][brushMask] = op.options['Block To Replace With'].ID
    chunk.Data[slices][brushMask] = op.options['Block To Replace With'].blockData

    createTileEntities(op.options['Block To Replace With'], brushBoxThisChunk, chunk)
