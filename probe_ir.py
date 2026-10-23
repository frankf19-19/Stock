import os, requests, json, re, io, urllib.parse, traceback, time
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
def N(s): print("::notice::" + str(s)[:900])
H = "https://mopsov.twse.com.tw"
try:
    for typek in ("sii", "otc"):
        r = requests.post(f"{H}/mops/web/ajax_t100sb02_1", headers=UA, timeout=60,
                          data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": typek, "year": "115", "month": "10"})
        t = r.text
        rows = [x for x in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S) if '<td' in x]
        files = re.findall(r'fileName\.value="([^"]+)"', t)
        N(f"{typek}: 列={len(rows)} 檔案={len(files)} 範例={files[:4]}")
        # 下載第一個
        for fn in files[:2]:
            for way in ("post", "get"):
                try:
                    if way == "post":
                        rr = requests.post(f"{H}/server-java/FileDownLoad", headers=UA, timeout=120,
                                           data={"step": "9", "filePath": "/home/html/nas/STR/", "fileName": fn, "functionName": "t100sb02_1"})
                    else:
                        rr = requests.get(f"{H}/nas/STR/{fn}", headers=UA, timeout=120)
                    b = rr.content
                    N(f"{fn} {way} {rr.status_code} {len(b)}B ct={rr.headers.get('Content-Type')} head={b[:6]}")
                    if b[:4] == b'%PDF':
                        from pypdf import PdfReader
                        rd = PdfReader(io.BytesIO(b)); tx = ''.join((pg.extract_text() or '') for pg in rd.pages[:6])
                        tx2 = re.sub(r'\s+', ' ', tx)[:600]; N(f"  pages={len(rd.pages)} text={tx2}")
                        break
                    if b[:2] == b'PK':
                        import zipfile
                        z = zipfile.ZipFile(io.BytesIO(b)); names = [n for n in z.namelist() if n.startswith('ppt/slides/slide')]
                        tx = ''
                        for n in sorted(names)[:6]:
                            tx += ' '.join(re.findall(r'<a:t>([^<]*)</a:t>', z.read(n).decode('utf-8', 'replace')))
                        tx2 = re.sub(r'\s+', ' ', tx)[:600]; N(f"  pptx slides={len(names)} text={tx2}")
                        break
                except Exception as e:
                    N(f"{fn} {way} ERR {str(e)[:150]}")
            time.sleep(2)
    # 影音連結/擇要訊息 欄位抽樣
    cells = [[re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', x, re.S)] for x in rows[:40]]
    vod = [c[9][:80] for c in cells if len(c) > 9 and 'http' in c[9]]
    N(f"影音連結有 {len(vod)}/{len(cells)}:{vod[:3]}")
except Exception:
    N('TRACE ' + traceback.format_exc()[-800:].replace('\n', ' | '))
