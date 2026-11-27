
from hashlib import sha256
from pathlib import Path
import shutil
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
import threading
from urllib.request import urlopen
from zipfile import ZipFile

URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.1-essentials_build.zip'
EXPECTED = 'b9bbbb3acece000cbeec994f856649354e52c773807841e78908374b24d658fd'
TOOLS = ('ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe')


def install(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='ffmpeg-download-',dir=directory.parent) as work:
        work = Path(work)
        archive = work/'ffmpeg.zip'
        digest = sha256()
        with urlopen(URL, timeout=45) as response, archive.open('wb') as output:
            size = int(response.headers.get('Content-Length') or 0)
            total = 0
            while True:
                data = response.read(1024*1024)
                if not data:
                    break
                total += len(data)
                digest.update(data)
                output.write(data)
                if size:
                    report(f'영상 도구 다운로드 중 · {total*100//size}%')
        if digest.hexdigest() != EXPECTED:
            raise ValueError('다운로드 파일을 확인하지 못했습니다. 인터넷 연결을 확인하고 다시 실행하세요.')
        report('영상 도구를 준비하는 중')
        with ZipFile(archive) as package:
            members = {}
            for name in TOOLS:
                matches = [item for item in package.namelist() if item.endswith('/bin/'+name)]
                if len(matches) != 1:
                    raise ValueError('필요한 영상 도구를 내려받지 못했습니다.')
                members[name] = matches[0]
            license = next((item for item in package.namelist() if item.endswith('/LICENSE')), None)
            if license:
                members['FFmpeg-LICENSE.txt'] = license
            for name, member in members.items():
                with package.open(member) as source, (work/name).open('wb') as output:
                    shutil.copyfileobj(source,output)
            for name in members:
                if not (directory/name).exists():
                    (work/name).replace(directory/name)


def setup(window, directory):
    import tkinter as tk
    from tkinter import messagebox, ttk
    if all((directory/name).is_file() for name in TOOLS):
        return True
    if not messagebox.askokcancel('영상 도구 준비',
          '처음 한 번 영상 도구를 내려받습니다(약 113MB). 인터넷에 연결한 뒤 진행해 주세요.',
          parent=window):
        return False
    dialog = tk.Toplevel(window)
    dialog.title('처음 실행 준비')
    dialog.resizable(False,False)
    dialog.protocol('WM_DELETE_WINDOW',lambda: None)
    status = tk.StringVar(value='영상 도구에 연결하는 중')
    ttk.Label(dialog,textvariable=status,padding=(32,20),width=40).pack()
    ttk.Progressbar(dialog,mode='indeterminate',length=270).pack(pady=(0,20))
    for widget in dialog.winfo_children():
        if isinstance(widget,ttk.Progressbar):
            widget.start(14)
    result = []
    updates = SimpleQueue()
    def worker():
        error = None
        try:
            install(directory, lambda text: updates.put(('progress',text)))
        except Exception as exc:
            error = str(exc)
        updates.put(('done',error))
    def finish(error):
        result.append(error)
        dialog.destroy()
    def poll():
        while True:
            try:
                kind, data = updates.get_nowait()
            except Empty:
                break
            if kind == 'done':
                finish(data)
                return
            status.set(data)
        window.after(120,poll)
    threading.Thread(target=worker,daemon=True).start()
    window.after(120,poll)
    window.wait_window(dialog)
    if result[0]:
        messagebox.showerror('영상 도구 다운로드',f'{result[0]}\n\n인터넷에 연결한 뒤 프로그램을 다시 실행하세요.',parent=window)
    return result[0] is None


