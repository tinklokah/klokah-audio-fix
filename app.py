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
st.set_page_config(page_title="第一課精確抓取", page_icon="🎯")
st.title("🎯 指定課項：01梅花般堅強 (專攻版)")

user_id = st.text_input("輸入帳號", value="pic11304")
target_list_id = "17849" # 第一課的 ID

if st.button(f"🔍 掃描第一課 (ID: {target_list_id})"):
    with st.spinner("正在鎖定第一課內容..."):
        url = f"https://web.klokah.tw/text/main.php?user={user_id}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 1. 鎖定包含 data-list="17849" 的那個 li 區塊
        # 根據原始碼，這課的所有單元都包在這個 li 裡面
        main_li = soup.find("li", class_="list-list") # 先找 list-list
        # 我們來回圈找正確的那一課
        target_container = None
        for li in soup.find_all("li", class_="list-list"):
            btn = li.find("button", attrs={"data-list": target_list_id})
            if btn:
                target_container = li
                break
        
        if target_container:
            # 2. 抓出裡面所有的單元按鈕
            unit_btns = target_container.find_all("button", class_="class-name-btn")
            
            st.write(f"### ✅ 成功鎖定：01梅花般堅強")
            st.write(f"共找到 {len(unit_btns)} 個單元：")
            
            lessons_to_process = []
            for b in unit_btns:
                tid = b.get('data-class')
                name = b.get_text(strip=True)
                st.write(f"- {name} (TID: {tid})")
                lessons_to_process.append({"tid": tid, "name": name})
            
            st.session_state.target_lessons = lessons_to_process
        else:
            st.error("找不到 ID 為 17849 的課程區塊，請確認帳號權限。")

# --- 批次處理與下載 ---
if 'target_lessons' in st.session_state:
    if st.button(f"🚀 開始後製這 {len(st.session_state.target_lessons)} 個單元"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, item in enumerate(st.session_state.target_lessons):
                st.write(f"處理中: {item['name']}")
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
        
        st.success("🎉 第一課後製完成！")
        st.download_button("⬇️ 下載第一課優化包", master_zip_io.getvalue(), "Lesson_01_Fixed.zip")
