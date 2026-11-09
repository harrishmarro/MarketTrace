import io
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from daily_data.nse_payload import csv_bytes
from daily_data.ingest import ingest
from daily_data.nse_series import parse

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def workbook(formula=False,multiple=False):
    fields=['SYMBOL','SERIES','DATE1','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY']
    values=['ABC','BE','08-Aug-2022','10.10','12.20','9.05','11.15','123456']
    def row(number,values,header):
        cells=[]
        for index,value in enumerate(values):
            letter=chr(65+index)
            if header or index<3:
                cells.append(f'<c r="{letter}{number}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                f='<f>1+1</f>' if formula and index==3 else ''
                cells.append(f'<c r="{letter}{number}">{f}<v>{value}</v></c>')
        return '<row>'+''.join(cells)+'</row>'
    sheet=f'<worksheet xmlns="{NS}"><sheetData>'+row(1,fields,True)+row(2,values,False)+'</sheetData></worksheet>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        sheets='<sheet name="prices"/>'* (2 if multiple else 1)
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{NS}"><sheets>{sheets}</sheets></workbook>')
        z.writestr('xl/worksheets/sheet1.xml',sheet)
    return out.getvalue()

class PayloadTests(unittest.TestCase):
    def test_excel_container_keeps_decimal_text_series_and_date(self):
        rows,bad=parse(workbook(),date(2022,8,9))
        self.assertEqual(rows[0]['open'],'10.10')
        self.assertEqual(rows[0]['series'],'BE')
        self.assertEqual(rows[0]['volume'],'123456')
        self.assertEqual(rows[0]['day'],'2022-08-08')
        self.assertFalse(bad)
    def test_formulas_and_ambiguous_workbooks_fail(self):
        for raw in (workbook(formula=True),workbook(multiple=True)):
            with self.assertRaises(ValueError):csv_bytes(raw)
    def test_ingestion_preserves_original_workbook_bytes(self):
        # EQ replacement is inside the fixture source, not a provider-data transformation.
        source=workbook()
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            contents={n:z.read(n) for n in z.namelist()}
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name,raw in contents.items(): z.writestr(name,raw.replace(b'<t>BE</t>',b'<t>EQ</t>'))
        raw=out.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'prices.sqlite')
            result=ingest(path,'nse',raw,'fixture',date(2022,8,9))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('select raw from batches').fetchone()[0],raw)
            self.assertEqual(result['bars'],1)

    def test_classic_bhavcopy_preserves_isin(self):
        raw=b'SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP,ISIN\nABC,BE,10,12,9,11,30,04-NOV-2021,INE123456789\n'
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('cm04NOV2021bhav.csv',raw)
        rows,bad=parse(out.getvalue(),date(2021,11,5))
        self.assertEqual(rows[0]['isin'],'INE123456789')
        self.assertEqual(rows[0]['day'],'2021-11-04')
        self.assertFalse(bad)
