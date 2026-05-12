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
st.title("⛏️ 深度挖掘：01梅花般堅強")

user_id = st.text_input("輸入帳號", value="pic11304")
target_list_id = "17849" # 第一課 ID

if st.button("🔍 執行特徵對位掃描"):
    with st.spinner("正在穿透 div.class-name 結構..."):
        try:
            url = f"https://web.klokah.tw/text/main.php?user={user_id}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers)
            res.encoding = 'utf-8'
            
            # 使用更穩定的解析方式
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 1. 先鎖定大標區塊
            target_area = None
            for li in soup.find_all("li", class_="list-list"):
                main_btn = li.find("button", attrs={"data-list": target_list_id})
                if main_btn:
                    target_area = li
                    break
            
            if target_area:
                # 2. 【核心改進】精準鎖定「單元按鈕」
                # 只找 class 同時包含 'class-name-btn' 和 'edit' 的按鈕
                # 這能排除掉旁邊的「觀看」、「編輯」、「更名」按鈕
                found_units = target_area.find_all("button", class_="class-name-btn edit")
                
                lessons = []
                st.write(f"### 📋 掃描成果：找到 {len(found_units)} 個單元")
                
                for b in found_units:
                    tid = b.get('data-class')
                    name = b.get_text(strip=True)
                    if tid:
                        st.write(f"- ✅ **{name}** (TID: {tid})")
                        lessons.append({"tid": tid, "name": name})
                
                st.session_state.target_lessons = lessons
            else:
                st.error("找不到該大標區塊，請確認帳號內容。")
        except Exception as e:
            st.error(f"掃描失敗：{e}")

# --- 批次處理 ---
if 'target_lessons' in st.session_state and st.session_state.target_lessons:
    if st.button(f"🚀 開始處理這 {len(st.session_state.target_lessons)} 個單元"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, item in enumerate(st.session_state.target_lessons):
                st.write(f"正在後製：{item['name']}")
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
        
        st.success("🎉 處理完畢！")
        st.download_button("⬇️ 下載 ZIP 包", master_zip_io.getvalue(), "Lesson_01_Fixed.zip")
