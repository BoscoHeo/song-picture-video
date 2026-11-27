
from pathlib import Path
import json
import subprocess
import tkinter as tk

from app import VideoApp
import engine

root = tk.Tk()
root.withdraw()
ui = VideoApp(root)
test_text = engine.ROOT.parent / 'portable-test-result.json'
engine.run([ui.ffmpeg, '-version'])
engine.run([ui.ffprobe, '-version'])
engine.run([ui.ffplay, '-version'])
assert engine.Image.__file__.startswith(str(engine.ROOT))
assert engine.pdfium.__file__.startswith(str(engine.ROOT))
from faster_whisper import WhisperModel
model = WhisperModel(str(engine.ROOT/'runtime'/'whisper-small'), device='cpu', compute_type='int8', cpu_threads=1)
assert model
languages = engine.run(['powershell.exe','-NoProfile','-Command',
    'Add-Type -AssemblyName System.Runtime.WindowsRuntime; [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]::AvailableRecognizerLanguages | ForEach-Object {$_.LanguageTag}']).decode('ascii',errors='replace').split()
ui.close()
test_text.write_text(json.dumps({'tk':True,'media_tools':True,'voice_model':True,'windows_ocr_languages':languages}), encoding='ascii')

