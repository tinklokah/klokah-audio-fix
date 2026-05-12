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

# --- v9.1 安全後製引擎 (不變) ---
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
st.set_page_config(page_title="族語教材精確後製器", page_icon="🎯")
st.title("🎯 族語教材：原樣目錄後製器")

if 'lesson_list' not in st.session_state:
    st.session_state.lesson_list = []

user_id = st.text_input("1. 輸入帳號 (如: pic11304)", value="pic11304")

if st.button("🔍 掃描教材清單"):
    if user_id:
        with st.spinner("正在解析下拉選單結構..."):
            try:
                url = f"https://web.klokah.tw/text/main.php?user={user_id}"
                headers = {'User-Agent': 'Mozilla/5.0'}
                res = requests.get(url, headers=headers)
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, "html.parser")
                
                found = []
                
                # 關鍵修改：尋找帶有 data-class 的按鈕 (這是真正的課程 ID)
                # 我們同時抓取它所屬的教材名稱 (span)
                items = soup.find_all("button", {"data-class": True})
                
                for item in items:
                    tid = item['data-class']
                    # 嘗試抓取這個按鈕顯示的文字 (例如: 01書名翻譯)
                    sub_name = item.get_text(strip=True)
                    
                    # 往上找大分類的名稱 (例如: 01中高級-梅花般堅強)
                    # 通常大分類會在同一個父層級的 span 裡
                    parent_section = item.find_parent("li") # 假設在 li 標籤內
                    main_name = ""
                    if parent_section:
                        main_span = parent_section.find("span", class_="list-name-sp")
                        if main_span:
                            main_name = main_span.get_text(strip=True)
                    
                    full_display_name = f"{main_name} > {sub_name}" if main_name else sub_name
                    
                    if tid not in [x['tid'] for x in found]:
                        found.append({"tid": tid, "name": full_display_name})
                
                # 如果找不到，嘗試更廣泛的搜尋
                if not found:
                    all_buttons = soup.find_all("button")
                    for b in all_buttons:
                        if b.has_attr('data-class'):
                            tid = b['data-class']
                            name = b.get_text(strip=True)
                            found.append({"tid": tid, "name": name})

                st.session_state.lesson_list = found
                if found:
                    st.success(f"成功找到 {len(found)} 個課程按鈕！")
                else:
                    st.error("找不到 data-class 按鈕。請確認是否已進到教材選擇頁面。")
            except Exception as e:
                st.error(f"連線失敗：{e}")

if st.session_state.lesson_list:
    st.write("---")
    st.write("### 2. 勾選欲處理課程：")
    select_all = st.checkbox("全選")
    selected = [l for l in st.session_state.lesson_list if st.checkbox(f"{l['name']} (ID: {l['tid']})", value=select_all)]

    if st.button(f"🚀 開始後製選定的 {len(selected)} 個課程"):
        if not selected:
            st.warning("請先勾選課程")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for idx, lesson in enumerate(selected):
                    st.write(f"處理中：{lesson['tid']}")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={lesson['tid']}"
                    try:
                        z_res = requests.get(zip_url, timeout=15)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        fixed = process_audio_bytes(sub_zip.read(f_name))
                                        orig_name = os.path.basename(f_name)
                                        # 保持數字資料夾
                                        master_zip.writestr(f"{lesson['tid']}/{orig_name}", fixed)
                    except:
                        st.warning(f"ID {lesson['tid']} 下載失敗")
                    p_bar.progress((idx + 1) / len(selected))
            
            st.success("✨ 處理完成！")
            st.download_button("⬇️ 下載 ZIP", master_zip_io.getvalue(), f"Fixed_{user_id}.zip")
