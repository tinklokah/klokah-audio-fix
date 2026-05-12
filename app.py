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

# --- v9.1 安全後製引擎 (音量平衡 + 降噪) ---
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

# --- 網頁介面佈局 ---
st.set_page_config(page_title="族語教材精確後製器", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語教材：14 課全自動後製下載")

if 'structured_data' not in st.session_state:
    st.session_state.structured_data = {}

user_id = st.text_input("輸入帳號 (如: pic11304)", value="pic11304")

if st.button("🔍 重新掃描所有教材結構"):
    if user_id:
        with st.spinner("正在解析大標與次標結構..."):
            try:
                url = f"https://web.klokah.tw/text/main.php?user={user_id}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                res = requests.get(url, headers=headers)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, "html.parser")
                
                # 建立結構字典
                new_structure = {}
                
                # 尋找所有教材的大外層 <li>
                list_items = soup.find_all("li", class_="list-list")
                
                for li in list_items:
                    # 1. 抓取大標題名稱
                    main_title_tag = li.find("span", class_="list-name-sp")
                    if not main_title_tag:
                        continue
                    main_title = main_title_tag.get_text(strip=True)
                    
                    # 2. 抓取該大標下方的所有次單元
                    sub_lessons = []
                    # 尋找 class-name-btn 且帶有 data-class 的按鈕
                    sub_btns = li.find_all("button", class_=re.compile(r"class-name-btn"))
                    
                    for btn in sub_btns:
                        if btn.has_attr('data-class'):
                            tid = btn['data-class']
                            sub_name = btn.get_text(strip=True)
                            sub_lessons.append({"tid": tid, "sub_name": sub_name})
                    
                    if sub_lessons:
                        new_structure[main_title] = sub_lessons

                st.session_state.structured_data = new_structure
                if new_structure:
                    st.success(f"成功！已掃描到 {len(new_structure)} 課教材。")
                else:
                    st.error("掃描不到結構，請確認網頁原始碼是否正確載入。")
            except Exception as e:
                st.error(f"連線出錯：{e}")

# --- 顯示帶有大標的勾選選單 ---
if st.session_state.structured_data:
    st.write("---")
    st.write("### 📂 請選擇欲處理的單元 (資料夾將維持數字 ID)")
    
    selected_list = []
    
    # 按照大標題分組顯示
    for main_title, units in st.session_state.structured_data.items():
        with st.expander(f"📘 {main_title}", expanded=True):
            cols = st.columns(3) # 三欄顯示節省空間
            for idx, unit in enumerate(units):
                col = cols[idx % 3]
                if col.checkbox(f"{unit['sub_name']}", key=f"cb_{unit['tid']}"):
                    selected_list.append(unit)

    st.write("---")
    
    if st.button(f"🚀 開始後製已選取的 {len(selected_list)} 個單元"):
        if not selected_list:
            st.warning("請先勾選單元！")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for i, unit in enumerate(selected_list):
                    st.write(f"正在下載與處理：{unit['sub_name']} (ID: {unit['tid']})")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={unit['tid']}"
                    try:
                        z_res = requests.get(zip_url, timeout=20)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        fixed = process_audio_bytes(sub_zip.read(f_name))
                                        # 檔名不變，資料夾使用數字 TID
                                        orig_filename = os.path.basename(f_name)
                                        master_zip.writestr(f"{unit['tid']}/{orig_filename}", fixed)
                    except:
                        st.warning(f"單元 {unit['tid']} 處理失敗，請稍後再試。")
                    p_bar.progress((i + 1) / len(selected_list))
            
            st.success("🎉 選定教材已全部優化完成！")
            st.download_button("⬇️ 下載 ZIP 優化包", master_zip_io.getvalue(), f"Klokah_Fixed_{user_id}.zip")
