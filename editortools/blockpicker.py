from albow import Label, TextFieldWrapped, Row, TableView, TableColumn, Column, Widget, Button, AttrRef, CheckBoxLabel
from albow.dialogs import Dialog
from editortools import thumbview
from editortools import blockview
from glbackground import GLBackground
from albow.root import get_root
from pymclevel.materials import Block, BlockstateAPI, id_limit, data_limit, id_limit_mask, data_limit_mask, getMaterials
from albow.translate import getLang

#&# Prototype for blocks/items names
import mclangres
#&#


def anySubtype(self):
    bl = Block(self.materials, self.ID, self.blockData)
    bl.wildcard = True
    return bl


Block.anySubtype = anySubtype
Block.wildcard = False  # True if


class BlockPicker(Dialog):
    is_gl_container = True

    def __init__(self, blockInfo, materials, *a, **kw):
        self.root = get_root()
        self.allowWildcards = False
        Dialog.__init__(self, *a, **kw)
        panelWidth = 518

        self.click_outside_response = 0
        self.materials = materials
        if materials.locked:
            self.previewMaterials = materials
        else:
            # pcm1k TODO - maybe have a "real" way to copy an MCMaterials?
            self.previewMaterials = getMaterials(materials.defsIds, forceNew=True)
        self.anySubtype = blockInfo.wildcard

        allBlocks = materials.allBlocks
        self.matchingBlocks = sorted(list(set(allBlocks)))
        #&#
        self.searchNames = [mclangres.translate(a.name).lower() for a in allBlocks]
        #&#

        try:
            self.selectedBlockIndex = self.matchingBlocks.index(blockInfo)
        except ValueError:
            self.selectedBlockIndex = 0
            for i, b in enumerate(self.matchingBlocks):
                if blockInfo.ID == b.ID and blockInfo.blockData == b.blockData:
                    self.selectedBlockIndex = i
                    break

        lbl = Label("Search")
        # lbl.rect.topleft = (0,0)

        fld = TextFieldWrapped(300)
        # fld.rect.topleft = (100, 10)
        # fld.centery = lbl.centery
        # fld.left = lbl.right

        fld.change_action = self.textEntered
        fld.enter_action = self.ok
        fld.escape_action = self.cancel
        fld.attention_lost = fld.commit

        self.awesomeField = fld

        searchRow = Row((lbl, fld))

        def formatBlockName(x):
            block = self.matchingBlocks[x]
            #&#
            #r = "{name}".format(name=block.name)
            r = u"{name}".format(name=mclangres.translate(block.name))
            #&#
            if bool(block.aka):
                #&#
                #r += " [{0}]".format(block.aka)
                r += u" [{0}]".format(mclangres.translate(block.aka))
                #&#

            return r

        def formatBlockID(x):
            block = self.matchingBlocks[x]
            ident = "({id}:{data})".format(
                id=block.ID if block.ID < id_limit else "?",
                data=block.blockData if block.blockData < data_limit else "?")
            return ident

        # pcm1k TODO - this should have the stringID
        tableview = TableView(columns=[TableColumn(" ", 24, "l", lambda x: ""),
                                       TableColumn("Name", 415, "l", formatBlockName),
                                       TableColumn("ID", 45, "l", formatBlockID)
                                       ])
        tableicons = [blockview.BlockView(materials) for i in xrange(tableview.rows.num_rows())]
        for t in tableicons:
            t.size = (16, 16)
            t.margin = 0
        spacing = max(tableview.font.get_linesize() - 16, 2)
        icons = Column(tableicons, spacing=spacing)

        # tableview.margin = 5
        tableview.num_rows = lambda: len(self.matchingBlocks)
        tableview.row_data = lambda x: (self.matchingBlocks[x], x, x)
        tableview.row_is_selected = lambda x: x == self.selectedBlockIndex
        tableview.click_row = self.selectTableRow
        draw_table_cell = tableview.draw_table_cell

        def draw_block_table_cell(surf, i, data, cell_rect, column):
            if isinstance(data, Block):
                tableicons[i - tableview.rows.scroll].blockInfo = data
            else:
                draw_table_cell(surf, i, data, cell_rect, column)

        tableview.draw_table_cell = draw_block_table_cell
        tableview.width = panelWidth
        tableview.anchor = "lrbt"
        # self.add(tableview)
        self.tableview = tableview
        tableWidget = Widget()
        tableWidget.add(tableview)
        tableWidget.shrink_wrap()

        def wdraw(*args):
            for t in tableicons:
                t.blockInfo = materials.Air

        tableWidget.draw = wdraw
        self.blockButton = blockView = thumbview.BlockThumbView(materials, self.blockInfo)

        blockView.centerx = self.centerx
        blockView.top = tableview.bottom

        # self.add(blockview)

        but = Button("OK")
        but.action = self.ok
        but.top = blockView.bottom
        but.centerx = self.centerx
        but.align = "c"
        but.height = 30

        if self.allowWildcards:
            # self.add(but)
            anyRow = CheckBoxLabel("Any Subtype", ref=AttrRef(self, 'anySubtype'),
                                   tooltipText="Replace blocks with any data value. Only useful for Replace operations.")
            col = Column((searchRow, tableWidget, anyRow, blockView, but))
        else:
            col = Column((searchRow, tableWidget, blockView, but))
        col.anchor = "wh"
        self.anchor = "wh"

        panel = GLBackground()
        panel.bg_color = [i / 255. for i in self.bg_color]
        panel.anchor = "tlbr"
        self.add(panel)

        self.add(col)
        self.add(icons)

        icons.left += tableview.margin + tableWidget.margin + col.margin
        icons.top = tableWidget.top + tableview.top + tableview.header_height + tableview.header_spacing + tableWidget.margin + tableview.margin + tableview.subwidgets[1].margin + (spacing / 2)

        self.shrink_wrap()
        panel.size = self.size

        try:
            self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
        except:
            pass

    @property
    def blockInfo(self):
        if bool(self.matchingBlocks):
            bl = self.matchingBlocks[self.selectedBlockIndex]
            if self.anySubtype:
                return bl.anySubtype()
            else:
                return bl

        else:
            return self.materials.Air

    def selectTableRow(self, i, e):
        oldIndex = self.selectedBlockIndex

        self.selectedBlockIndex = i
        self.blockButton.blockInfo = self.blockInfo
        if e.num_clicks > 1 and oldIndex == i:
            self.ok()

    def textEntered(self):
        text = self.awesomeField.text
        blockData = None
        materials = self.materials
        try:
            textSplit = text.rsplit(":", 1)
            if len(textSplit) == 2:
                text2, num = textSplit
                blockData = int(num) & data_limit_mask
                # only actually set the text if the above succeeds
                text = text2
            blockID = int(text) & id_limit_mask

            block = materials.blockWithID(blockID, blockData)

            self.matchingBlocks = [block]
            self.selectedBlockIndex = 0
            self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
            self.blockButton.blockInfo = self.blockInfo

            return
        except ValueError:
            pass
        except Exception as e:
            print repr(e)

        if bool(text):
            previewMaterials = self.previewMaterials
            if getLang() == 'en_US':
                matches = materials.blocksMatching(text)
            else:
                matches = materials.blocksMatching(text, self.searchNames)

#            matches = (materials if blockData is None else previewMaterials).blocksMatching(text,
#                names=self.searchNames if getLang() != "en_US" else None)
            matches = materials.blocksMatching(text,
                names=self.searchNames if getLang() != "en_US" else None)

            stringID, properties = BlockstateAPI.deStringifyBlockstate(text)
            with previewMaterials.tempBlocks():
                stateID, stateData = previewMaterials.blockstate_api.blockstateToID(stringID, properties, create=True)
            if stateID != -1 and stateData != -1:
                matches.append(previewMaterials.blockWithID(stateID, stateData))

            if blockData is not None:
                ids = set(b.ID for b in matches)
                matches = [previewMaterials.blockWithID(id, blockData) for id in ids]
        else:
            matches = materials.allBlocks

        self.matchingBlocks = sorted(list(set(matches)))
        self.selectedBlockIndex = 0

        self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
        self.blockButton.blockInfo = self.blockInfo

    def dispatch_key(self, name, evt):
        super(BlockPicker, self).dispatch_key(name, evt)
        if name == "key_down":
            keyname = self.root.getKey(evt)
            if keyname == "Up" and self.selectedBlockIndex > 0:
                self.selectedBlockIndex -= 1
                self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
                self.blockButton.blockInfo = self.blockInfo
            elif keyname == "Down" and self.selectedBlockIndex < len(self.matchingBlocks) - 1:
                self.selectedBlockIndex += 1
                self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
                self.blockButton.blockInfo = self.blockInfo
            elif keyname == 'Page down':
                self.selectedBlockIndex = min(len(self.matchingBlocks) - 1, self.selectedBlockIndex + self.tableview.rows.num_rows())
                self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
                self.blockButton.blockInfo = self.blockInfo
            elif keyname == 'Page up':
                self.selectedBlockIndex = max(0, self.selectedBlockIndex - self.tableview.rows.num_rows())
                self.tableview.rows.scroll_to_item(self.selectedBlockIndex)
                self.blockButton.blockInfo = self.blockInfo
            if self.tableview.rows.cell_to_item_no(0, 0) != None and (self.tableview.rows.cell_to_item_no(0, 0) + self.tableview.rows.num_rows() -1 > self.selectedBlockIndex or self.tableview.rows.cell_to_item_no(0, 0) + self.tableview.rows.num_rows() -1 < self.selectedBlockIndex):
                self.tableview.rows.scroll_to_item(self.selectedBlockIndex)

    def ok(self):
        blockInfo = self.blockInfo
        materials = self.materials
        if blockInfo.materials is not materials:
            stateID, stateData = materials.blockstate_api.blockstateToID(*blockInfo.Blockstate, create=True)
            if stateID != -1 and stateData != -1:
                self.matchingBlocks = [materials.blockWithID(stateID, stateData)]
            else:
                self.matchingBlocks = []
            self.selectedBlockIndex = 0
        super(BlockPicker, self).ok()
