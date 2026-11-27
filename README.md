# 노래 그림 영상 만들기

음원과 PDF 또는 JPG·JPEG·PNG 그림으로 16:9 풀 HD MP4 영상을 만드는 Windows 앱입니다.

## 다운로드

[최신 릴리즈](https://github.com/BoscoHeo/song-picture-video/releases/latest)에서 Windows x64 경량판 ZIP을 받아 전체를 압축 해제하고 `노래 그림 영상 만들기.exe`를 실행하세요.

- 첫 실행에 영상 도구를 약 113MB 내려받습니다.
- 음원으로부터 가사를 처음 자동 인식할 때 약 486MB의 음성 모델을 받습니다. SRT를 사용하거나 시간을 직접 지정하면 음성 모델은 필요하지 않습니다.
- 한국어 그림 문구 인식에는 Windows의 한국어 OCR 기능이 필요합니다.
- 입력한 음원과 그림은 PC에서 처리합니다. 가사와 그림을 자동으로 연결한 뒤 확인 표시가 있는 구간을 검토할 수 있습니다.

## 소스 실행

Windows x64에서 Tk가 포함된 Python 3.12를 사용하세요. 저장소 루트에서 다음 명령을 실행합니다.

```powershell
python -m pip install -r requirements.txt
python app/app.py
```

Windows용 실행 파일의 소스는 `launcher/LiteLauncher.cs`에 있습니다. 릴리즈 ZIP에는 Python과 실행에 필요한 라이브러리가 포함되어 있습니다.

이 프로젝트는 [FFmpeg Windows 빌드](https://www.gyan.dev/ffmpeg/builds/)와 [faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)을 사용합니다.

