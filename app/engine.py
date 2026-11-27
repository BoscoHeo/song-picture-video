from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import lru_cache
import json
from math import ceil, cos, pi
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unicodedata

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'runtime' / 'speech'))

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
import pypdfium2 as pdfium

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ROTATIONS = (0, 90, 180, 270)


@dataclass
class Picture:
    path: Path
    label: str
    angle: int = 0
    text: str = ''
    start: float = 0
    note: str = ''


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


def run(args, cwd=None):
    result = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, cwd=cwd)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip()[-1500:]
                           or '파일을 처리하지 못했습니다.')
    return result.stdout


def natural(path):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r'(\d+)', Path(path).name)]


def load_pictures(paths, directory):
    pictures = []
    for path in sorted(map(Path, paths), key=natural):
        if path.suffix.lower() == '.pdf':
            with pdfium.PdfDocument(path) as doc:
                for number in range(len(doc)):
                    target = directory / f'page_{len(pictures):04}.jpg'
                    page = doc[number]
                    bitmap = page.render(scale=1850 / max(page.get_size()))
                    bitmap.to_pil().convert('RGB').save(target, quality=96, subsampling=0)
                    bitmap.close()
                    page.close()
                    pictures.append(Picture(target, f'{path.stem} · {number+1}쪽'))
        else:
            with Image.open(path) as image:
                image.verify()
            pictures.append(Picture(path, path.name))
    return pictures


def picture_image(item):
    with Image.open(item.path) as original:
        return ImageOps.exif_transpose(original).convert('RGB').rotate(item.angle, expand=True)


@lru_cache(maxsize=16000)
def clean(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


@lru_cache(maxsize=90000)
def similarity(left, right):
    if not left or not right:
        return 0
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    return matcher.ratio() if matcher.quick_ratio() >= .48 else 0


def ocr_batch(folder):
    raw = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(ROOT / 'ocr.ps1'), '-Folder', str(folder)])
    return [json.loads(row) for row in raw.decode('utf-8-sig').splitlines()]


def read_pictures(pictures, directory, tell):
    with TemporaryDirectory(dir=directory) as folder:
        folder = Path(folder)
        for index, item in enumerate(pictures):
            if index % 12 == 0:
                tell(f'그림 읽는 중 ({index+1}/{len(pictures)})')
            original = picture_image(replace(item, angle=0))
            original.thumbnail((1500, 1500), Image.Resampling.LANCZOS)
            for angle in ROTATIONS:
                image = original.rotate(angle, expand=True)
                gray = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=.5)
                gray.save(folder / f'{index:04}-{angle:03}.jpg', quality=92)
        recognized = {}
        for item in ocr_batch(folder):
            page, angle = map(int, item['file'].split('-'))
            lines = [(line['text'], line['y']) for line in item['lines'] if clean(line['text'])]
            def quality(line):
                text, y = line
                length = len(clean(text))
                return min(length, 32) + sum('가' <= c <= '힣' for c in text) * .33 + (8 if y > .67 else 0)
            quality_lines = sorted(lines, key=quality, reverse=True)
            score = sum(quality(line) / (i+1) for i, line in enumerate(quality_lines[:4]))
            bottom = [line for line in lines if line[1] > .61 and len(clean(line[0])) >= 3]
            words = [line[0] for line in sorted(bottom or quality_lines[:2], key=quality, reverse=True)[:4]]
            recognized.setdefault(page, {})[angle] = score, words
    strong_angles = []
    for options in recognized.values():
        ranked = sorted(options, key=lambda angle: options[angle][0], reverse=True)
        if options[ranked[0]][0] - options[ranked[1]][0] >= 12:
            strong_angles.append(ranked[0])
    default = max(ROTATIONS, key=strong_angles.count)
    if strong_angles.count(default) < max(3, len(pictures) * .30):
        default = None
    same_scan = (default is not None and len(pictures) >= 5
                 and all(item.label.rsplit(' · ',1)[-1].endswith('쪽') for item in pictures)
                 and strong_angles.count(default) >= .83*len(strong_angles))
    readings = []
    for index, item in enumerate(pictures):
        options = recognized[index]
        best = max(ROTATIONS, key=lambda angle: options[angle][0])
        if default is not None and options[best][0] < options[default][0] + (32 if same_scan else 16):
            best = default
        elif options[best][0] < 8:
            best = item.angle
        item.angle = best
        readings.append(options[best][1])
    with TemporaryDirectory(dir=directory) as folder:
        folder = Path(folder)
        tell('그림 아래쪽의 흐린 문구를 한 번 더 읽는 중')
        for i, item in enumerate(pictures):
            image = picture_image(item)
            w, h = image.size
            region = image.crop((0,round(h*.68),w,h))
            red, green, blue = region.split()
            contrast = ImageChops.darker(ImageChops.darker(red,green),blue)
            contrast = contrast.point([max(0, min(255, (value-217)*4+217)) for value in range(256)])
            contrast = contrast.resize((1800, max(1, round(1800*contrast.height/contrast.width))),
                                       Image.Resampling.LANCZOS)
            contrast.save(folder / f'{i:04}.jpg', quality=94)
        for result in ocr_batch(folder):
            extra = [line['text'] for line in result['lines'] if len(clean(line['text'])) >= 5][-4:]
            index = int(result['file'])
            readings[index] = list(dict.fromkeys([*readings[index], *extra]))[:8]
    for item, lines in zip(pictures, readings):
        item.text = ' / '.join(lines[:5])
    return readings


def probe(ffprobe, audio):
    raw = run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
               'stream=codec_name,duration:format=duration', '-of', 'json', str(audio)])
    info = json.loads(raw)
    if not info.get('streams'):
        raise ValueError('선택한 파일에 오디오가 없습니다.')
    audio_stream = info['streams'][0]
    duration = float(info['format']['duration'])
    if duration <= 0:
        raise ValueError('음원 길이를 읽을 수 없습니다.')
    return duration, audio_stream['codec_name']


def speech(audio, tell, ffmpeg='ffmpeg', language=None):
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    from faster_whisper import WhisperModel
    import numpy as np
    models = ROOT / 'runtime'
    small_path = models / 'whisper-small'
    if not all((small_path / name).is_file() for name in ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')):
        from faster_whisper.utils import download_model
        tell('음성 인식 모델 다운로드 중 · 처음 한 번 인터넷 연결 필요')
        download_model('small', output_dir=str(small_path), revision='536b0662742c02347bc0e980a01041f333bce120')
    model = WhisperModel(str(small_path), device='cpu', compute_type='int8',
                         cpu_threads=min(6, os.cpu_count() or 2))
    tell('음원에서 가사를 읽는 중')
    pcm = run([ffmpeg, '-v', 'error', '-i', str(audio), '-map', '0:a:0',
               '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'])
    samples = np.frombuffer(pcm, dtype='<f4')
    segments, _ = model.transcribe(samples, language=language, beam_size=2, temperature=0,
                                  word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    words = []
    for segment in segments:
        if segment.words:
            words.extend(Word(word.start, word.end, word.word) for word in segment.words)
        elif segment.text.strip():
            words.append(Word(segment.start, segment.end, segment.text))
        tell(f'가사 읽는 중 · {segment.end:.0f}초까지')
    return words


def srt_cues(path):
    pattern = r'(\d+:\d\d:\d\d[,.]\d+)\s*-->\s*(\d+:\d\d:\d\d[,.]\d+)[^\n]*\n([\s\S]+?)(?=\n\s*\n|\Z)'
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r', '')
    def seconds(stamp):
        hours, minutes, sec = stamp.replace(',', '.').split(':')
        return int(hours)*3600 + int(minutes)*60 + float(sec)
    cues = [(seconds(start), seconds(end), re.sub('<[^>]+>', '', lyric).replace('\n', ' '))
            for start, end, lyric in re.findall(pattern, text)]
    if not cues:
        raise ValueError('SRT 파일에서 시간과 가사를 읽을 수 없습니다.')
    return [Word(start, end, lyric) for start, end, lyric in sorted(cues) if end > start]


def match_pictures(pictures, readings, words, duration, pair_size):
    words = [word for word in words if clean(word.text) and 0 <= word.start < duration]
    words.sort(key=lambda word: word.start)
    labels = [[clean(line) for line in lines if len(clean(line)) >= 3] for lines in readings]
    windows = []
    for start, word in enumerate(words):
        text = ''
        options = []
        for end in range(start, min(start+13, len(words))):
            current = words[end]
            if current.end - word.start > 13 or (end > start and current.start - words[end-1].end > 2.7):
                break
            text += clean(current.text)
            if len(text) >= 3:
                options.append((end+1, text))
        windows.append(options)

    # A monotone matching keeps identical choruses in their source order.
    # A pair uses a single word span and cannot reuse a span from an earlier pair.
    best_plan = (0, {})
    for offset in range(min(pair_size, len(pictures))):
        groups = [list(range(index, min(index+pair_size, len(pictures))))
                  for index in range(offset, len(pictures), pair_size)]
        states = {0: (0, {})}
        for group in groups:
            texts = [labels[index] for index in group if labels[index]]
            if not texts:
                continue
            previous = states
            states = previous.copy()
            state_list = sorted(previous)
            visited, strongest = 0, (0, {})
            for start, choices in enumerate(windows):
                while visited < len(state_list) and state_list[visited] <= start:
                    state = previous[state_list[visited]]
                    if state[0] > strongest[0]:
                        strongest = state
                    visited += 1
                for end, text in choices:
                    scores = [max((similarity(text, line) for line in lines
                                   if .5 <= len(line)/len(text) <= 1.85), default=0)
                              for lines in texts]
                    score = max(scores)
                    if score < .67:
                        continue
                    relative = abs(words[start].start / duration - group[0] / len(pictures))
                    corroboration = sum(value >= .72 for value in scores) - (score >= .72)
                    strength = strongest[0] + (score-.57)*2 + .11*corroboration - .16*relative
                    if strength > states.get(end, (0, {}))[0]:
                        states[end] = strength, {**strongest[1], group[0]: (group, start, end, score)}
        plan = max(states.values(), key=lambda state: state[0])
        if plan[0] > best_plan[0]:
            best_plan = plan

    matches = list(best_plan[1].values())
    if not matches and words and abs(ceil(len(pictures) / pair_size) - len(words)) <= 2:
        matches = [(list(range(i*pair_size, min((i+1)*pair_size, len(pictures)))), i, i+1, .60)
                   for i in range(min(len(words), ceil(len(pictures) / pair_size)))]
    anchors = {0: 0, len(pictures): duration}
    for item in pictures:
        item.note = '시간·그림 확인'
    for position, (group, start, end, score) in enumerate(matches):
        word = words[start]
        first = group[0]
        following = matches[position+1] if position+1 < len(matches) else None
        boundary = (words[following[1]].start if following and following[0][0] == group[-1]+1
                    else min(duration, words[end-1].end + .35))
        span = max(.1, boundary-word.start)
        for i, index in enumerate(group):
            anchors[index] = word.start + span*i/len(group)
            pictures[index].note = '가사 연결' if score >= .80 and labels[index] else '가사 연결 확인'
    anchors[0] = 0
    if matches:
        first = matches[0][0][0]
        last = matches[-1][0][-1]+1
        tail = max(words[-1].end, words[matches[-1][2]-1].end)
        if first and words[matches[0][1]].start <= max(22, duration*.10):
            for item in pictures[:first]:
                item.note = '전주 후보 · 확인'
        if last < len(pictures) and duration-tail >= 1.5:
            anchors[last] = min(duration-.1, max(tail+.15, anchors[last-1]+.15))
            for item in pictures[last:]:
                item.note = '후주 후보 · 확인'
    points = sorted(anchors)
    for index, end in zip(points, points[1:]):
        lo, hi = anchors[index], anchors[end]
        for number in range(index, end):
            pictures[number].start = lo+(hi-lo)*(number-index)/(end-index)
    for index in range(len(pictures)-1, 0, -1):
        limit = (pictures[index+1].start if index+1 < len(pictures) else duration) - .042
        pictures[index].start = min(pictures[index].start, limit)
    if len(pictures) > 1 and pictures[1].start <= 0:
        even_timeline(pictures, duration)
    return len(matches)


def even_timeline(pictures, duration):
    for index, item in enumerate(pictures):
        item.start = duration * index/len(pictures)
        item.note = '균등 배치 · 확인'


def art_frame(item, size):
    image = picture_image(item)
    w, h = size
    image.thumbnail((round(w*.96), round(h*.95)), Image.Resampling.LANCZOS)
    x, y = (w-image.width)//2, (h-image.height)//2
    background = Image.new('RGB', size, '#edeae3')
    shadow = Image.new('L', size)
    ImageDraw.Draw(shadow).rectangle((x, y+2, x+image.width, y+image.height+4), fill=65)
    background.paste('#514c43', (0, 0, w, h), shadow.filter(ImageFilter.GaussianBlur(max(2, h//80))))
    background.paste(image, (x, y))
    return background


def export(ffmpeg, audio, codec, pictures, duration, output, dissolve, tell, size=(1920, 1080)):
    fps = 24
    output = Path(output).resolve()
    audio = Path(audio).resolve()
    starts = [round(item.start*fps) for item in pictures] + [ceil(duration*fps)]
    if starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError('첫 그림은 0초, 나머지는 음원 끝보다 이른 증가 순서여야 합니다. 그림 사이를 0.05초 이상 띄우세요.')
    with TemporaryDirectory(prefix='song-story-') as directory:
        directory = Path(directory)
        previous = None
        rows = ['ffconcat version 1.0']
        def add(file, frames):
            rows.extend((f"file '{file}'", f'option framerate {fps}', f'duration {frames/fps:.9f}'))
        for i, item in enumerate(pictures):
            tell(f'영상 그림 준비 중 ({i+1}/{len(pictures)})')
            image = art_frame(item, size)
            length = starts[i+1]-starts[i]
            blend = min(round(dissolve*fps), max(0,length-1)) if previous is not None else 0
            for step in range(1, blend+1):
                name = f'f{i:04}_{step:02}.jpg'
                alpha = (1-cos(pi*step/(blend+1)))*.5
                Image.blend(previous, image, alpha).save(directory/name, quality=92, subsampling=0)
                add(name, 1)
            last = f'f{i:04}.jpg'
            image.save(directory/last, quality=95, subsampling=0)
            add(last, length-blend)
            previous = image
        add(last, 1)
        timeline = directory / 'timeline.txt'
        timeline.write_text('\n'.join(rows)+'\n', encoding='ascii')
        tell('MP4 저장 중')
        audio_options = ['-c:a', 'copy'] if codec in ('aac', 'mp3', 'alac') else ['-c:a', 'aac', '-b:a', '256k']
        partial = output.with_name(f'.{output.stem}.in-progress.mp4')
        if partial.exists():
            raise FileExistsError(f'같은 이름의 저장 작업이 있습니다. 다른 이름을 선택하세요.\n{partial}')
        try:
            run([ffmpeg, '-v', 'error', '-f', 'concat', '-safe', '0', '-i', timeline.name,
                 '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-map_metadata', '-1',
                 '-vf', f'fps={fps},format=yuv420p', '-frames:v', str(starts[-1]),
                 '-c:v', 'libx264', '-threads', '6', '-preset', 'veryfast', '-crf', '18',
                 *audio_options, '-movflags', '+faststart', str(partial)], cwd=directory)
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)



