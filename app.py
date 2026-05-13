import streamlit as st
import requests
import io
import os
import json
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
import zipfile

# --- v9.1 安全後製引擎 ---
def process_audio_bytes(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        # 轉 wav 處理
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        # 降噪
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.72)
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        # 裁切靜音
        intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
        valid = [i for i in intervals if (i[1] - i[0]) > 100]
        if valid:
            min_v = min(audio[s:e].dBFS for s, e in valid)
            audio = audio + max(-2.0, min(-8.0 - min_v, 15.0))
            audio = audio.compress_dynamic_range(threshold=-7.0, ratio=8.0, attack=10.0, release=60.0)
            audio = audio + (-6.0 - audio.max_dBFS)
            audio = audio[max(0, valid[0][0]-300) : min(len(audio), valid[-1][1]+300)]
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 網頁介面 ---
st.set_page_config(page_title="路徑直取優化器", page_icon="🎵")
st.title("🎵 族語教材：音檔路徑直取優化器")

st.info("直接貼入包含音檔路徑的 JSON 資料，我會直接抓取 MP3 並進行優化。")

raw_json = st.text_area("請在此貼上 API 回傳的完整 JSON 內容", height=300)

if st.button("🔍 解析路徑並準備抓取"):
    if not raw_json:
        st.error("請提供資料內容")
    else:
        try:
            data = json.loads(raw_json)
            audio_tasks = []

            # 遞迴掃描所有的音檔路徑
            def scan_for_audio(obj, current_unit=""):
                if isinstance(obj, dict):
                    # 抓取單元名稱作為資料夾名
                    unit_name = obj.get('title') or obj.get('name') or current_unit
                    
                    # 搜尋可能的音檔欄位 (例如: audio, mp3, path, file)
                    for k, v in obj.items():
                        if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                            # 補全網址 (假設 JSON 裡是相對路徑)
                            full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                            audio_tasks.append({
                                "url": full_url,
                                "folder": unit_name,
                                "filename": os.path.basename(v)
                            })
                        else:
                            scan_for_audio(v, unit_name)
                elif isinstance(obj, list):
                    for item in obj:
                        scan_for_audio(item, current_unit)

            scan_for_audio(data)
            
            if audio_tasks:
                st.session_state.audio_tasks = audio_tasks
                st.success(f"✅ 發現了 {len(audio_tasks)} 個音檔路徑！")
            else:
                st.warning("資料中找不到音檔路徑 (.mp3)，請確認 JSON 內容。")
        except Exception as e:
            st.error(f"解析失敗：{e}")

# --- 下載與處理 ---
if 'audio_tasks' in st.session_state:
    st.write("---")
    if st.button(f"🚀 開始抓取並後製這 {len(st.session_state.audio_tasks)} 個檔案"):
        master_zip_io = io.BytesIO()
        success_count = 0
        
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, task in enumerate(st.session_state.audio_tasks):
                st.write(f"處理中: {task['filename']}")
                try:
                    r = requests.get(task['url'], timeout=10)
                    if r.status_code == 200:
                        # 進行後製
                        fixed = process_audio_bytes(r.content)
                        # 依照單元名稱存放
                        save_path = f"{task['folder']}/{task['filename']}"
                        master_zip.writestr(save_path, fixed)
                        success_count += 1
                except:
                    st.error(f"無法抓取: {task['url']}")
                p_bar.progress((idx + 1) / len(st.session_state.audio_tasks))

        if success_count > 0:
            st.success(f"🎉 大功告成！成功後製了 {success_count} 個音檔。")
            st.download_button("⬇️ 下載優化音檔包", master_zip_io.getvalue(), "Klokah_Audio_Fixed.zip")
