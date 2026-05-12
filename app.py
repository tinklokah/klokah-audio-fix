import streamlit as st
import requests
from bs4 import BeautifulSoup
import io
import zipfile
import os
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# --- v9.1 安全後製引擎 ---
def process_audio_bytes(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.72)
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
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
st.set_page_config(page_title="第一課全量提取", page_icon="⛏️")
st.title("⛏️ 終極掃描：01梅花般堅強")

user_id = st.text_input("輸入帳號", value="pic11304")

if st.button("🔍 執行地毯式全網頁掃描"):
    with st.spinner("正在搜尋所有單元 ID..."):
        try:
            url = f"https://web.klokah.tw/text/main.php?user={user_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            res = requests.get(url, headers=headers)
            res.encoding = 'utf-8'
            
            # 使用最寬容的解析器
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 1. 暴力搜尋：找出整頁所有帶有 data-class 的 button
            all_btns = soup.find_all("button", attrs={"data-class": True})
            
            lessons = []
            st.write(f"### 📋 原始按鈕分析 (共找到 {len(all_btns)} 個按鈕)")
            
            # 2. 針對我們關心的 ID 範圍進行過濾 (74770 ~ 74775)
            # 這是你提供的 HTML 中第一課的 ID 範圍
            target_ids = ["74770", "74771", "74772", "74773", "74774", "74775"]
            
            for b in all_btns:
                tid = b.get('data-class')
                if tid in target_ids:
                    # 只有名稱按鈕會包含「數字」開頭（如 01、02...）
                    name = b.get_text(strip=True)
                    if name and any(char.isdigit() for char in name[:2]):
                        # 避免抓到重複的 (因為同 ID 可能有觀看、編輯等按鈕)
                        if not any(l['tid'] == tid for l in lessons):
                            st.write(f"📍 找到單元：{name} (TID: {tid})")
                            lessons.append({"tid": tid, "name": name})
            
            st.session_state.target_lessons = lessons
            
            if not lessons:
                st.error("在地毯式搜尋中仍未發現目標單元，可能網頁原始碼被加密或未載入。")
                # 除錯用：印出前 10 個找到的 data-class
                st.write("前 5 個找到的 ID 範例：", [btn.get('data-class') for btn in all_btns[:5]])
                
        except Exception as e:
            st.error(f"掃描出錯：{e}")

# --- 下載處理 ---
if 'target_lessons' in st.session_state and st.session_state.target_lessons:
    if st.button(f"🚀 批次優化這 {len(st.session_state.target_lessons)} 個單元"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, item in enumerate(st.session_state.target_lessons):
                st.write(f"正在處理：{item['name']}")
                zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={item['tid']}"
                try:
                    z_res = requests.get(zip_url, timeout=20)
                    with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                        for f_name in sub_zip.namelist():
                            if f_name.lower().endswith('.mp3'):
                                fixed = process_audio_bytes(sub_zip.read(f_name))
                                master_zip.writestr(f"01_梅花般堅強/{item['tid']}/{os.path.basename(f_name)}", fixed)
                except: pass
                p_bar.progress((idx + 1) / len(st.session_state.target_lessons))
        
        st.success("🎉 下載準備就緒！")
        st.download_button("⬇️ 下載成果", master_zip_io.getvalue(), "Lesson_01_Fixed.zip")
