from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as core
from PIL import ImageTk


def clock(seconds):
    return f'{int(seconds//60):02}:{seconds%60:05.2f}'


def parse_time(value):
    parts = value.strip().replace(',', '.').split(':')
    if len(parts) == 2:
        return 60*int(parts[0]) + float(parts[1])
    return float(parts[0])


def binaries():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg와 FFprobe를 찾지 못했습니다. 실행 파일 안내를 확인하세요.')
    return tuple(shutil.which(name) for name in ('ffmpeg', 'ffprobe', 'ffplay'))


class VideoApp:
    def __init__(self, window):
        self.window = window
        self.temp = tempfile.TemporaryDirectory(prefix='song-picture-')
        self.directory = Path(self.temp.name)
        self.pictures = []
        self.audio = None
        self.subtitles = None
        self.duration = 0
        self.codec = ''
        self.position = 0
        self.process = None
        self.started = 0
        self.busy = False
        self.last_preview = None
        self.ffmpeg, self.ffprobe, self.ffplay = binaries()
        self.window.title('노래 그림 영상 만들기')
        self.window.geometry('1190x755')
        self.window.minsize(960, 650)
        self.window.configure(bg='#f4f4ef')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.setup()
        self.tick()

    def setup(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Malgun Gothic', 10))
        style.configure('TFrame', background='#f4f4ef')
        style.configure('TLabel', background='#f4f4ef', foreground='#1e312b')
        style.configure('Title.TLabel', font=('Malgun Gothic', 21, 'bold'))
        style.configure('Accent.TButton', background='#215747', foreground='white', padding=(15,8))
        style.map('Accent.TButton', background=[('active','#2b6d5a'),('disabled','#7d948c')],
                  foreground=[('disabled','#ededed')])
        style.configure('Treeview', rowheight=27, fieldbackground='#ffffff', background='#ffffff')
        style.map('Treeview', background=[('selected','#d4e9df')], foreground=[('selected','#18372b')])

        page = ttk.Frame(self.window, padding=(22, 17))
        page.pack(fill='both', expand=True)
        ttk.Label(page, text='노래 그림 영상 만들기', style='Title.TLabel').pack(anchor='w')
        bar = ttk.Frame(page, padding=(0,12))
        bar.pack(fill='x')
        self.buttons = []
        for label, action in [('음원 선택', self.choose_audio), ('PDF 선택', self.choose_pdf),
                              ('JPG 여러 장 선택', self.choose_images), ('가사 SRT 선택', self.choose_subtitles)]:
            self.button(bar, label, action).pack(side='left', padx=(0,6))
        self.button(bar, '자동 배치', self.analyze, accent=True).pack(side='right')
        self.pair_size = tk.IntVar(value=2)
        ttk.Spinbox(bar, from_=1, to=12, width=4, textvariable=self.pair_size).pack(side='right', padx=(5,12))
        ttk.Label(bar, text='가사당 그림 수').pack(side='right')
        self.inputs = tk.StringVar(value='음원과 PDF 또는 JPG를 선택하세요.')
        ttk.Label(page, textvariable=self.inputs, wraplength=1050).pack(anchor='w', pady=(0,12))

        split = ttk.Panedwindow(page, orient='horizontal')
        split.pack(fill='both', expand=True)
        edit = ttk.Frame(split, padding=(0,0,12,0))
        display = ttk.Frame(split, padding=(12,0,0,0))
        split.add(edit, weight=4)
        split.add(display, weight=3)
        grid = ttk.Frame(edit)
        grid.pack(fill='both', expand=True)
        self.table = ttk.Treeview(grid, columns=('page','start','text','note'), show='headings', selectmode='browse')
        for key, title, width, minimum, stretch in (
            ('page','그림',128,75,True), ('start','시작',74,69,False),
            ('text','읽은 문구',190,90,True), ('note','상태',125,102,False)
        ):
            self.table.heading(key,text=title)
            self.table.column(key,width=width,minwidth=minimum,stretch=stretch)
        self.table.tag_configure('review', foreground='#8b4b14')
        scroller = ttk.Scrollbar(grid, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroller.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroller.pack(side='right', fill='y')
        self.table.bind('<<TreeviewSelect>>', self.on_select)
        self.table.bind('<Double-1>', lambda _: self.time_entry.focus_set())
        editbar = ttk.Frame(edit, padding=(0,8,0,0))
        editbar.pack(fill='x')
        for label, action in [('위로', lambda: self.move(-1)), ('아래로', lambda: self.move(1)),
                              ('선택 회전', self.rotate), ('전체 회전', lambda: self.rotate(True))]:
            self.button(editbar,label,action).pack(side='left', padx=(0,5))
        timebar = ttk.Frame(edit, padding=(0,7,0,0))
        timebar.pack(fill='x')
        ttk.Label(timebar,text='그림 시작 시각').pack(side='left', padx=(0,6))
        self.time_entry = ttk.Entry(timebar, width=11)
        self.time_entry.pack(side='left', padx=(0,6))
        self.time_entry.bind('<Return>', lambda _: self.apply_time())
        self.button(timebar,'시간 적용',self.apply_time).pack(side='left',padx=(0,5))
        self.button(timebar,'재생 위치로 지정',self.mark_time).pack(side='left')

        ttk.Label(display,text='그림 미리보기',font=('Malgun Gothic',12,'bold')).pack(anchor='w',pady=(0,7))
        self.canvas = tk.Canvas(display, bg='#dedcd4', borderwidth=0, highlightthickness=0, height=300)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.refresh_preview(True))
        self.slider = ttk.Scale(display, from_=0, to=1)
        self.slider.pack(fill='x',pady=(8,3))
        self.slider.bind('<ButtonPress-1>', self.pause_for_seek)
        self.slider.bind('<B1-Motion>', self.scrub)
        self.slider.bind('<ButtonRelease-1>', self.finish_seek)
        playback = ttk.Frame(display)
        playback.pack(fill='x')
        self.play_button = self.button(playback,'재생',self.toggle_play)
        self.play_button.pack(side='left')
        self.button(playback,'선택 그림 위치로',self.jump_to_selection).pack(side='left',padx=6)
        self.timer = tk.StringVar(value='00:00.00 / 00:00.00')
        ttk.Label(playback,textvariable=self.timer).pack(side='right')

        footer = ttk.Frame(page,padding=(0,13,0,0))
        footer.pack(fill='x')
        self.status = tk.StringVar(value='준비')
        ttk.Label(footer, textvariable=self.status, wraplength=650).pack(side='left',anchor='w')
        self.button(footer,'MP4 저장',self.save,accent=True).pack(side='right')
        self.dissolve = tk.StringVar(value='0.30')
        ttk.Spinbox(footer,from_=0,to=2,increment=.1, textvariable=self.dissolve,width=5).pack(side='right',padx=7)
        ttk.Label(footer,text='전환(초)').pack(side='right')

    def button(self, parent, label, action, accent=False):
        button = ttk.Button(parent,text=label,command=action,style='Accent.TButton' if accent else 'TButton')
        self.buttons.append(button)
        return button

    def background(self, task, done):
        if self.busy:
            return
        self.pause()
        self.busy = True
        for button in self.buttons:
            button.state(['disabled'])
        def tell(message):
            self.window.after(0, self.status.set, message)
        def worker():
            try:
                result = task(tell)
            except Exception as exc:
                self.window.after(0, finish, None, str(exc))
            else:
                self.window.after(0, finish, result, None)
        def finish(result, error):
            self.busy = False
            for button in self.buttons:
                button.state(['!disabled'])
            if error is not None:
                self.status.set('처리 중 문제가 생겼습니다.')
                messagebox.showerror('처리 오류',error,parent=self.window)
            else:
                done(result)
        threading.Thread(target=worker,daemon=True).start()

    def choose_audio(self):
        path = filedialog.askopenfilename(filetypes=[('음원','*.mp3 *.m4a *.wav *.flac *.aac *.ogg *.wma *.opus *.mp4'),('모든 파일','*.*')])
        if not path:
            return
        try:
            duration,codec = core.probe(self.ffprobe,path)
        except Exception as exc:
            messagebox.showerror('음원 확인',str(exc),parent=self.window)
            return
        self.pause()
        if self.audio and Path(path) != self.audio:
            self.subtitles = None
        self.audio,self.duration,self.codec,self.position = Path(path),duration,codec,0
        self.slider.configure(to=duration)
        self.slider.set(0)
        if self.pictures:
            core.even_timeline(self.pictures,duration)
        self.caption()
        self.refresh()

    def choose_pdf(self):
        path = filedialog.askopenfilename(filetypes=[('PDF 파일','*.pdf')])
        if path:
            self.open_pictures([path])

    def choose_images(self):
        items = filedialog.askopenfilenames(filetypes=[('JPG · PNG 그림','*.jpg *.jpeg *.png'),('모든 파일','*.*')])
        if items:
            self.open_pictures(items)

    def open_pictures(self, paths):
        self.status.set('그림을 불러오는 중')
        def done(pictures):
            self.pictures = pictures
            if self.duration:
                core.even_timeline(pictures,self.duration)
            self.caption()
            self.refresh(0)
            self.status.set(f'그림 {len(pictures)}장 · 자동 배치를 누르세요.')
        self.background(lambda _: core.load_pictures(paths,self.directory), done)

    def choose_subtitles(self):
        path = filedialog.askopenfilename(filetypes=[('가사 SRT','*.srt')])
        if path:
            self.subtitles = Path(path)
            self.caption()

    def caption(self):
        parts = [f'음원 · {self.audio.name} ({clock(self.duration)})' if self.audio else '음원 선택 대기',
                 f'그림 · {len(self.pictures)}장' if self.pictures else '그림 선택 대기']
        if self.subtitles:
            parts.append(f'가사 · {self.subtitles.name}')
        self.inputs.set('     |     '.join(parts))

    def analyze(self):
        if not self.audio or not self.pictures:
            messagebox.showinfo('파일 선택','음원과 그림을 먼저 선택하세요.',parent=self.window)
            return
        try:
            pair_size=self.pair_size.get()
            if not 1 <= pair_size <= 12:
                raise ValueError()
        except (ValueError,tk.TclError):
            messagebox.showinfo('그림 수','가사당 그림 수는 1~12장입니다.',parent=self.window)
            return
        self.status.set('자동 배치를 준비 중')
        items = [replace(item) for item in self.pictures]
        def task(tell):
            errors=[]
            try:
                readings=core.read_pictures(items,self.directory,tell)
            except Exception as exc:
                readings=[[] for _ in items]
                errors.append('그림 문구를 읽을 수 없습니다. Windows 한국어 OCR을 확인하세요.\n'+str(exc))
            try:
                all_text = ''.join(line for lines in readings for line in lines)
                letters = sum(char.isalpha() for char in all_text)
                hangul = sum('가' <= char <= '힣' for char in all_text)
                language = 'ko' if hangul >= 15 and hangul > .45*letters else None
                words=core.srt_cues(self.subtitles) if self.subtitles else core.speech(self.audio,tell,self.ffmpeg,language)
            except Exception as exc:
                words=[]
                errors.append('음원 가사를 읽을 수 없습니다. 가사 SRT 또는 음원 인식 모델을 확인하세요.\n'+str(exc))
            tell('가사와 그림을 순서대로 연결하는 중')
            count=core.match_pictures(items,readings,words,self.duration,pair_size)
            return items,count,errors
        def done(result):
            self.pictures,count,errors=result
            self.refresh(0)
            self.caption()
            review=sum('확인' in item.note for item in self.pictures)
            self.status.set(f'가사 {count}개 구간 연결 · 그림 {review}장 확인 필요')
            if errors:
                messagebox.showwarning('자동 배치 일부 완료','\n\n'.join(errors),parent=self.window)
        self.background(task,done)

    def selection(self):
        values=self.table.selection()
        return int(values[0]) if values else None

    def refresh(self, selected=None):
        if selected is None:
            selected=self.selection()
        self.table.delete(*self.table.get_children())
        for i,item in enumerate(self.pictures):
            label=item.label.rsplit(' · ',1)[-1]
            self.table.insert('','end',iid=str(i),values=(label,clock(item.start),item.text,item.note),
                              tags=('review',) if '확인' in item.note else ())
        if selected is not None and selected < len(self.pictures):
            self.table.selection_set(str(selected))
            self.table.see(str(selected))
        self.refresh_preview(True)

    def on_select(self, _=None):
        selected=self.selection()
        if selected is not None:
            self.time_entry.delete(0,'end')
            self.time_entry.insert(0,clock(self.pictures[selected].start))
        self.refresh_preview(True)

    def move(self, amount):
        if self.busy:
            return
        index=self.selection()
        if index is None or not 0 <= index+amount < len(self.pictures):
            return
        other=index+amount
        a,b=self.pictures[index],self.pictures[other]
        self.pictures[index],self.pictures[other]=replace(b,start=a.start,note='순서 변경'),replace(a,start=b.start,note='순서 변경')
        self.refresh(other)

    def rotate(self, all_pages=False):
        if self.busy:
            return
        index=self.selection()
        if index is None and not all_pages:
            return
        items=self.pictures if all_pages else [self.pictures[index]]
        for item in items:
            item.angle=(item.angle+90)%360
        self.refresh_preview(True)

    def apply_time(self, value=None):
        if self.busy:
            return
        index=self.selection()
        if index is None or not self.duration:
            return
        try:
            stamp=parse_time(self.time_entry.get()) if value is None else value
            lower=self.pictures[index-1].start+.05 if index else 0
            upper=(self.pictures[index+1].start if index+1<len(self.pictures) else self.duration)-.05
            if (index == 0 and stamp != 0) or not lower-1e-8 <= stamp <= upper+1e-8:
                raise ValueError()
        except ValueError:
            messagebox.showinfo('시작 시간','첫 그림은 00:00.00입니다. 나머지 그림은 앞뒤 그림과 0.05초 이상 간격을 두세요.',parent=self.window)
            return
        self.pictures[index].start=stamp
        self.pictures[index].note='직접 지정'
        self.refresh(index)

    def mark_time(self):
        self.apply_time(round(self.position,2))

    def refresh_preview(self, force=False):
        self.timer.set(f'{clock(self.position)} / {clock(self.duration)}')
        index=self.selection()
        if self.process is not None or index is None:
            index=next((i for i in range(len(self.pictures)-1,-1,-1) if self.pictures[i].start <= self.position),None)
        if not force and index == self.last_preview:
            return
        self.last_preview=index
        self.canvas.delete('all')
        w,h=max(10,self.canvas.winfo_width()),max(10,self.canvas.winfo_height())
        if index is None:
            self.canvas.create_text(w/2,h/2,text='그림을 불러오면 여기에 표시됩니다.',fill='#4d6258',font=('Malgun Gothic',10))
            return
        width=min(w,round(h*16/9))
        height=min(h,round(w*9/16))
        self.photo=ImageTk.PhotoImage(core.art_frame(self.pictures[index],(width,height)))
        self.canvas.create_image(w/2,h/2,image=self.photo)

    def pause(self):
        if self.process is not None:
            self.position=min(self.duration,self.position+max(0,time.monotonic()-self.started))
            self.process.terminate()
            self.process=None
        self.play_button.configure(text='재생')

    def toggle_play(self):
        if self.busy or not self.audio:
            return
        if self.process is not None:
            self.pause()
            self.refresh_preview(True)
            return
        if not self.ffplay:
            messagebox.showinfo('음원 재생','FFplay를 찾지 못했습니다. FFmpeg 폴더에서 FFplay를 함께 사용하세요.',parent=self.window)
            return
        if self.position >= self.duration-.05:
            self.position=0
        self.process=subprocess.Popen([self.ffplay,'-v','error','-nodisp','-autoexit','-vn',
                                       '-ss',f'{self.position:.3f}',str(self.audio)],
                                      creationflags=core.NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.started=time.monotonic()
        self.play_button.configure(text='일시정지')
        self.refresh_preview(True)

    def pause_for_seek(self, _):
        self.pause()
        self.window.after_idle(self.scrub)

    def scrub(self, _=None):
        if not self.duration:
            return
        self.position=float(self.slider.get())
        self.refresh_preview(True)
        self.show_playhead()

    def show_playhead(self):
        index=next((i for i in range(len(self.pictures)-1,-1,-1) if self.pictures[i].start <= self.position),None)
        if index is not None:
            self.table.selection_set(str(index))
            self.table.see(str(index))

    def finish_seek(self, _):
        self.scrub()

    def jump_to_selection(self):
        index=self.selection()
        if index is not None:
            self.pause()
            self.position=self.pictures[index].start
            self.slider.set(self.position)
            self.refresh_preview(True)

    def tick(self):
        if self.process is not None:
            now=time.monotonic()
            elapsed=max(0,now-self.started)
            self.position=min(self.duration,self.position+elapsed)
            self.started=now
            self.slider.set(self.position)
            if self.process.poll() is not None or self.position>=self.duration:
                self.pause()
            self.refresh_preview()
        self.window.after(100,self.tick)

    def save(self):
        if not self.audio or not self.pictures:
            messagebox.showinfo('파일 선택','음원과 그림을 먼저 선택하세요.',parent=self.window)
            return
        try:
            dissolve=float(self.dissolve.get().replace(',','.'))
            if not 0 <= dissolve <= 2:
                raise ValueError()
        except ValueError:
            messagebox.showinfo('전환 시간','0~2초 사이로 입력하세요.',parent=self.window)
            return
        output=filedialog.asksaveasfilename(defaultextension='.mp4',filetypes=[('MP4 영상','*.mp4')],
                                            initialfile=self.audio.stem+' - 그림 영상.mp4')
        if not output:
            return
        items=[replace(item) for item in self.pictures]
        def job(tell):
            core.export(self.ffmpeg,self.audio,self.codec,items,self.duration,output,dissolve,tell)
        def done(_):
            copied=self.codec in ('aac','mp3','alac')
            self.status.set('저장 완료 · 원본 오디오 유지' if copied else '저장 완료 · 오디오를 AAC로 변환')
            if messagebox.askyesno('저장 완료',f'{Path(output).name}\n\n저장한 영상을 열까요?',parent=self.window):
                os.startfile(output)
        self.background(job,done)

    def close(self):
        if self.busy:
            messagebox.showinfo('작업 중','현재 처리가 끝나면 닫을 수 있습니다.',parent=self.window)
            return
        self.pause()
        self.temp.cleanup()
        self.window.destroy()


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if '--self-test' in sys.argv:
        import portable_check
        raise SystemExit(0)
    import media_setup
    root=tk.Tk()
    root.withdraw()
    tools = core.ROOT.parent / 'runtime' / 'ffmpeg' / 'bin'
    if not media_setup.setup(root, tools):
        root.destroy()
        raise SystemExit(0)
    os.environ['PATH'] = str(tools) + os.pathsep + os.environ.get('PATH', '')
    root.deiconify()
    try:
        application=VideoApp(root)
    except Exception as error:
        root.withdraw()
        messagebox.showerror('프로그램 실행',str(error),parent=root)
        root.destroy()
    else:
        root.mainloop()




