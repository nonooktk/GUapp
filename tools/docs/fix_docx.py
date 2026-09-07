# -*- coding: utf-8 -*-
# 既存 docx の Word レイアウト破壊要因を修復する（再生成せずに XML を直接直す）
#  1) 異常な w:tblInd（EMU を dxa と誤認した巨大値）を削除
#  2) w:tblPr の子要素をスキーマ順に並べ替え（tblCellMar が tblLook の後ろにあった）
#  3) 空の w:fldSimple に結果ランを追加
#  4) settings.xml に w:view=print を保証
import sys, zipfile, shutil, re, os
from lxml import etree
sys.stdout.reconfigure(encoding='utf-8')

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
def q(t): return '{%s}%s' % (W, t)

TBLPR_ORDER = ['tblStyle','tblpPr','tblOverlap','bidiVisual','tblStyleRowBandSize','tblStyleColBandSize',
               'tblW','jc','tblCellSpacing','tblInd','tblBorders','shd','tblLayout','tblCellMar','tblLook',
               'tblCaption','tblDescription']

def fix_document_xml(xml_bytes):
    root = etree.fromstring(xml_bytes)
    n_ind = n_reorder = n_fld = 0
    for tblPr in root.iter(q('tblPr')):
        for ind in tblPr.findall(q('tblInd')):
            try: v = int(ind.get(q('w')))
            except: v = 0
            if v > 20000 or v < -20000:   # 1 ページ幅（約 11000 dxa）を超える字下げは異常
                tblPr.remove(ind); n_ind += 1
        children = list(tblPr)
        def key(el):
            tag = etree.QName(el).localname
            return TBLPR_ORDER.index(tag) if tag in TBLPR_ORDER else 99
        ordered = sorted(children, key=key)
        if [etree.QName(c).localname for c in children] != [etree.QName(c).localname for c in ordered]:
            for c in children: tblPr.remove(c)
            for c in ordered: tblPr.append(c)
            n_reorder += 1
    for fld in root.iter(q('fldSimple')):
        if len(fld) == 0:
            r = etree.SubElement(fld, q('r')); t = etree.SubElement(r, q('t')); t.text = '1'; n_fld += 1
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True), (n_ind, n_reorder, n_fld)

def fix_settings(xml_bytes):
    root = etree.fromstring(xml_bytes)
    if root.find(q('view')) is None:
        v = etree.Element(q('view')); v.set(q('val'), 'print'); root.insert(0, v)
    else:
        root.find(q('view')).set(q('val'), 'print')
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

def fix(path):
    tmp = path + '.tmp'
    zin = zipfile.ZipFile(path)
    zout = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
    report = {}
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == 'word/document.xml' or re.match(r'word/(header|footer)\d*\.xml', item.filename):
            data, stats = fix_document_xml(data); report[item.filename] = stats
        elif item.filename == 'word/settings.xml':
            data = fix_settings(data)
        zout.writestr(item, data)
    zin.close(); zout.close()
    shutil.move(tmp, path)
    return report

if __name__ == '__main__':
    for p in sys.argv[1:]:
        rep = fix(p)
        print(os.path.basename(p), '→', {k.split('/')[-1]: v for k, v in rep.items() if any(v)})
