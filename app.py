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

# --- 網頁介面 ---
st.set_page_config(page_title="族語教材精確後製器", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語教材：14 課全量深度掃描器")

if 'structured_data' not in st.session_state:
    st.session_state.structured_data = {}

user_id = st.text_input("輸入帳號 (如: pic11304)", value="pic11304")

if st.button("🔍 地毯式掃描所有教材"):
    if user_id:
        with st.spinner("正在執行全網域掃描，請稍候..."):
            try:
                url = f"https://web.klokah.tw/text/main.php?user={user_id}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                res = requests.get(url, headers=headers)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, "html.parser")
                
                # 最終存放結果：{ 大標: [ {tid, sub_name}, ... ] }
                final_map = {}

                # 邏輯：直接找出頁面上所有具備 data-class 的次標按鈕
                all_sub_btns = soup.find_all("button", attrs={"data-class": True})
                
                for btn in all_sub_btns:
                    tid = btn['data-class']
                    sub_name = btn.get_text(strip=True)
                    
                    # 關鍵：往上尋找最近的大標題容器 li.list-list
                    parent_li = btn.find_parents("li", class_="list-list")
                    if parent_li:
                        # 在這個特定的 li 裡面找它的大標名稱
                        main_tag = parent_li[0].find("span", class_="list-name-sp")
                        main_title = main_tag.get_text(strip=True) if main_tag else "未分類教材"
                    else:
                        main_title = "其他教材"

                    if main_title not in final_map:
                        final_map[main_title] = []
                    
                    # 避免重複加入
                    if tid not in [x['tid'] for x in final_map[main_title]]:
                        final_map[main_title].append({"tid": tid, "sub_name": sub_name})

                st.session_state.structured_data = final_map
                
                if final_map:
                    st.success(f"成功！已掃描到 {len(final_map)} 課教材，共計 {sum(len(v) for v in final_map.values())} 個單元。")
                else:
                    st.error("掃描不到任何單元。")
            except Exception as e:
                st.error(f"連線出錯：{e}")

# --- 介面呈現 ---
if st.session_state.structured_data:
    st.write("---")
    selected_list = []
    
    for main_title, units in st.session_state.structured_data.items():
        with st.expander(f"📘 {main_title}", expanded=True):
            # 這裡我們用多列佈局，讓 6 個單元能整齊排開
            cols = st.columns(3)
            for idx, unit in enumerate(units):
                with cols[idx % 3]:
                    if st.checkbox(f"{unit['sub_name']}", key=f"cb_{unit['tid']}"):
                        selected_list.append(unit)

    st.write("---")
    
    if st.button(f"🚀 開始後製選取的 {len(selected_list)} 個單元"):
        if not selected_list:
            st.warning("請先勾選單元！")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for i, unit in enumerate(selected_list):
                    st.write(f"處理中：{unit['sub_name']} ({unit['tid']})")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={unit['tid']}"
                    try:
                        z_res = requests.get(zip_url, timeout=20)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        fixed = process_audio_bytes(sub_zip.read(f_name))
                                        orig_filename = os.path.basename(f_name)
                                        master_zip.writestr(f"{unit['tid']}/{orig_filename}", fixed)
                    except: pass
                    p_bar.progress((i + 1) / len(selected_list))
            
            st.success("🎉 全部處理完成！")
            st.download_button("⬇️ 下載 ZIP", master_zip_io.getvalue(), f"Klokah_Fixed_{user_id}.zip")
