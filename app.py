import streamlit as st
import requests
import io
import os
import zipfile
import subprocess
import time

# --- 核心後製：全 FFmpeg 濾鏡處理 ---
def process_audio_pure_ffmpeg(audio_bytes, filename):
    timestamp = int(time.time() * 1000)
    temp_in = f"in_{timestamp}.mp3"
    temp_out = f"out_{timestamp}.mp3"
    
    try:
        with open(temp_in, "wb") as f:
            f.write(audio_bytes)

        # FFmpeg 濾鏡鏈說明：
        # 1. silenceremove: 去除前後空白 (只留約 0.2s)
        # 2. afftdn: 非 AI 頻譜降噪 (效果純淨，不吃資源)
        # 3. loudnorm: 專業平衡 (I=-18, TP=-6, LRA=7, precision=0.1)
        
        filter_str = (
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB," # 去頭
            "areverse,"                                                            # 翻轉去尾
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB,"
            "areverse,"                                                            # 翻轉回來
            "afftdn=nr=12:nt=w,"                                                  # 降噪
            "loudnorm=I=-18:TP=-6:LRA=7:measured_I=-18:measured_TP=-6"            # 音量平衡
        )

        cmd = [
            "ffmpeg", "-y", "-i", temp_in,
            "-af", filter_str,
            "-ar", "44100", "-b:a", "192k", temp_out
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)

        with open(temp_out, "rb") as f:
            return f.read()

    except Exception as e:
        st.error(f"處理失敗: {e}")
        return audio_bytes
    finally:
        for t in [temp_in, temp_out]:
            if os.path.exists(t): os.remove(t)

# --- 介面部分 (延用穩定勾選架構) ---
st.set_page_config(page_title="族語音訊雲端後製", layout="wide")
st.title("🎙️ 族語音訊雲端後製：FFmpeg 專業平衡版")

# [狀態初始化與 API 抓取邏輯，保持與前一版本一致...]
# (此處省略 API 抓取與勾選顯示程式碼，請延用上一版 OK 的部分)

# --- 執行按鈕 ---
# 假設 final_selection 是你勾選後的清單
if st.button("🚀 執行雲端後製並下載"):
    final_selection = [t for t in st.session_state.tasks if st.session_state.get(f"chk_{t['url']}", False)]
    if not final_selection:
        st.warning("請先勾選檔案")
    else:
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            st_text = st.empty()
            for i, task in enumerate(final_selection):
                st_text.text(f"雲端處理中: {task['file']}")
                r = requests.get(task['url'])
                if r.status_code == 200:
                    # 呼叫 FFmpeg 處理
                    processed = process_audio_pure_ffmpeg(r.content, task['file'])
                    master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                p_bar.progress((i + 1) / len(final_selection))
            st_text.text("✨ 處理完成！")
        st.download_button("⬇️ 下載後製包", zip_io.getvalue(), "processed_audio.zip")
