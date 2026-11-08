"""Bounded NSE container decoding. Original bytes remain authoritative provenance."""
import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
LIMIT=50_000_000


def csv_bytes(raw):
    if not raw.startswith(b'PK'): return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        if sum(i.file_size for i in infos)>LIMIT: raise ValueError('Expanded NSE container too large')
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate ZIP members')
        if 'xl/workbook.xml' not in names:
            files=[n for n in names if n.lower().endswith('.csv')]
            if len(files)!=1: raise ValueError('Expected one bounded CSV')
            return z.read(files[0])
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        sheets=workbook.findall('s:sheets/s:sheet',NS)
        files=[n for n in names if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n)]
        if len(sheets)!=1 or len(files)!=1: raise ValueError('Expected one worksheet')
        shared=[]
        if 'xl/sharedStrings.xml' in names:
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            shared=[''.join(n.text or '' for n in s.findall('.//s:t',NS)) for s in root.findall('s:si',NS)]
        root=ET.fromstring(z.read(files[0]))
        output=io.StringIO();writer=csv.writer(output)
        for row in root.findall('s:sheetData/s:row',NS):
            values={}
            for cell in row.findall('s:c',NS):
                if cell.find('s:f',NS) is not None: raise ValueError('Formula in NSE source worksheet')
                ref=cell.get('r','');m=re.fullmatch(r'([A-Z]+)[1-9]\d*',ref)
                if not m: raise ValueError('Invalid worksheet cell reference')
                index=0
                for letter in m[1]: index=index*26+ord(letter)-64
                if index>64 or index in values: raise ValueError('Unsupported worksheet columns')
                kind=cell.get('t','n');v=cell.find('s:v',NS)
                value='' if v is None or v.text is None else v.text
                if kind=='s':
                    if not value.isdigit() or int(value)>=len(shared): raise ValueError('Invalid shared string index')
                    value=shared[int(value)]
                elif kind=='inlineStr': value=''.join(n.text or '' for n in cell.findall('.//s:t',NS))
                elif kind not in ('n','str'): raise ValueError('Unsupported worksheet value type')
                values[index]=value
            writer.writerow([values.get(i,'') for i in range(1,max(values,default=0)+1)])
        return output.getvalue().encode('utf-8')
