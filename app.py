def process_audio_brickwall(audio_bytes):
    try:
        # 讀取音檔
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. 基礎降噪 (維持清晰度)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 強力壓縮 (先把高低落差縮小，避免小聲的部分聽不到)
        audio = audio.compress_dynamic_range(
            threshold=-24.0, 
            ratio=6.0, 
            attack=5.0, 
            release=100.0
        )

        # 3. 【核心需求】暴力調大音量 (Gain)
        # 我們先假設增加 15dB，讓原本細小的波形撐開
        audio = audio + 15 

        # 4. 【核心需求】超過 -6dB 的部分削掉 (Limiting)
        # 用 normalize 設定頂部死線，headroom=6.0 意思就是最高只能到 -6dB
        # 如果波形超過了，它會被強制壓回這個平面
        audio = audio.normalize(headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes
