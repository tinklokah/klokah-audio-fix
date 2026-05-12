import streamlit as st
import requests
from bs4 import BeautifulSoup
import io
import zipfile
import re
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
st.set_page_config(page_title="族語教材精準掃描器", page_icon="📑", layout="wide")
st.title("📑 族語教材：大標/次標全量抓取器")

if 'structured_data' not in st.session_state:
    st.session_state.structured_data = {}

user_id = st.text_input("輸入帳號 (如: pic11304)", value="pic11304")

if st.button("🔍 開始掃描 (尋找 class-name-btn)"):
    if user_id:
        with st.spinner("正在解析網頁結構..."):
            try:
                url = f"https://web.klokah.tw/text/main.php?user={user_id}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                res = requests.get(url, headers=headers)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, "html.parser")
                
                final_map = {}
                # 1. 遍歷每一個課程區塊
                containers = soup.find_all("li", class_="list-list")
                
                for container in containers:
                    # 2. 抓大標 (01中高級-梅花般堅強)
                    title_tag = container.find("span", class_="list-name-sp")
                    if not title_tag:
                        continue
                    main_title = title_tag.get_text(strip=True)
                    
                    # 3. 抓這個區塊內所有的次標 (01書名翻譯...)
                    # 我們直接鎖定你說的 class-name-btn
                    unit_btns = container.find_all("button", class_=lambda x: x and 'class-name-btn' in x)
                    
                    lessons = []
                    for btn in unit_btns:
                        tid = btn.get('data-class')
                        # 確保只抓按鈕本身的文字，排除子標籤可能產生的雜訊
                        unit_name = btn.get_text(strip=True)
                        
                        if tid and unit_name:
                            lessons.append({"tid": tid, "sub_name": unit_name})
                    
                    if lessons:
                        final_map[main_title] = lessons

                st.session_state.structured_data = final_map
                
                if final_map:
                    st.success(f"成功找到 {len(final_map)} 課教材！")
                else:
                    st.error("找不到教材內容，請確認帳號是否正確或網頁已載入。")
            except Exception as e:
                st.error(f"掃描失敗：{e}")

# --- 顯示勾選介面 ---
if st.session_state.structured_data:
    st.write("---")
    st.info("請勾選想要處理的單元，下載後會按 ID 分資料夾存放。")
    
    selected_units = []
    for main_title, units in st.session_state.structured_data.items():
        # 使用大標題作為摺疊選單
        with st.expander(f"📘 {main_title}", expanded=True):
            # 每行顯示 3 個單元
            cols = st.columns(3)
            for i, unit in enumerate(units):
                with cols[i % 3]:
                    if st.checkbox(f"{unit['sub_name']}", key=f"unit_{unit['tid']}"):
                        selected_units.append(unit)

    st.write("---")
    if st.button(f"🚀 開始後製處理 ({len(selected_units)} 個項目)"):
        if not selected_units:
            st.warning("請至少勾選一個單元")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for idx, unit in enumerate(selected_units):
                    st.write(f"正在處理：{unit['sub_name']} (ID: {unit['tid']})")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={unit['tid']}"
                    try:
                        z_res = requests.get(zip_url, timeout=15)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        fixed_audio = process_audio_bytes(sub_zip.read(f_name))
                                        # 存入 ZIP：{TID}/{原始檔名}
                                        master_zip.writestr(f"{unit['tid']}/{os.path.basename(f_name)}", fixed_audio)
                    except:
                        st.error(f"單元 {unit['tid']} 下載異常")
                    p_bar.progress((idx + 1) / len(selected_units))
            
            st.success("✨ 優化完成！")
            st.download_button("⬇️ 點此下載 ZIP 包", master_zip_io.getvalue(), f"Klokah_Fixed_{user_id}.zip")
