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
st.set_page_config(page_title="全量教材抓取器", page_icon="🗂️", layout="wide")
st.title("🗂️ 族語教材：全課項地毯式掃描")

if 'all_units' not in st.session_state:
    st.session_state.all_units = []

user_id = st.text_input("輸入帳號", value="pic11304")

if st.button("🔍 執行全量深度掃描"):
    with st.spinner("正在強制提取所有單元，請稍候..."):
        try:
            url = f"https://web.klokah.tw/text/main.php?user={user_id}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            res = requests.get(url, headers=headers)
            res.encoding = 'utf-8'
            
            # 使用更寬容的解析器
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 💡 核心邏輯：不再管 li 或 div 的層級
            # 直接找頁面上「所有」具備 class-name-btn 類別的 button
            raw_btns = soup.find_all("button", class_=lambda x: x and 'class-name-btn' in x)
            
            final_list = []
            for btn in raw_btns:
                tid = btn.get('data-class')
                name = btn.get_text(strip=True)
                
                if tid and name:
                    # 嘗試往上找最近的大標題，增加識別度
                    parent_area = btn.find_parents("li", class_="list-list")
                    main_title = "未知課程"
                    if parent_area:
                        title_tag = parent_area[0].find("span", class_="list-name-sp")
                        if title_tag:
                            main_title = title_tag.get_text(strip=True)
                    
                    final_list.append({"tid": tid, "name": name, "main": main_title})

            # 移除重複項
            unique_results = []
            seen_tids = set()
            for item in final_list:
                if item['tid'] not in seen_tids:
                    unique_results.append(item)
                    seen_tids.add(item['tid'])

            st.session_state.all_units = unique_results
            if unique_results:
                st.success(f"掃描完畢！共抓到 {len(unique_results)} 個單元。")
            else:
                st.error("掃描結果為 0，請檢查帳號或網頁原始碼。")
        except Exception as e:
            st.error(f"連線或解析失敗：{e}")

# --- 顯示與勾選 ---
if st.session_state.all_units:
    st.write("---")
    
    # 按大標題分組顯示
    grouped = {}
    for u in st.session_state.all_units:
        grouped.setdefault(u['main'], []).append(u)
    
    selected_items = []
    
    # 增加「全選」按鈕
    col_ctrl1, col_ctrl2 = st.columns([1, 5])
    if col_ctrl1.button("全部選取"):
        st.session_state.selected_all = True
    
    for main_title, units in grouped.items():
        with st.expander(f"📘 {main_title}", expanded=True):
            cols = st.columns(3)
            for i, unit in enumerate(units):
                with cols[i % 3]:
                    # 如果點了全部選取，則預設勾選
                    is_checked = st.checkbox(f"{unit['name']}", key=f"chk_{unit['tid']}")
                    if is_checked:
                        selected_items.append(unit)

    st.write("---")
    if st.button(f"🚀 開始批次後製 ({len(selected_items)} 個項目)"):
        if not selected_items:
            st.warning("請先勾選單元")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for idx, item in enumerate(selected_items):
                    st.write(f"正在處理: {item['main']} > {item['name']}")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={item['tid']}"
                    try:
                        z_res = requests.get(zip_url, timeout=20)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        fixed = process_audio_bytes(sub_zip.read(f_name))
                                        # 存放在：大標/TID_檔名
                                        safe_main = "".join(x for x in item['main'] if x.isalnum())
                                        master_zip.writestr(f"{safe_main}/{item['tid']}_{os.path.basename(f_name)}", fixed)
                    except: pass
                    p_bar.progress((idx + 1) / len(selected_items))
            
            st.success("✨ 優化完成！")
            st.download_button("⬇️ 下載最終 ZIP 總包", master_zip_io.getvalue(), "Klokah_Full_Collection.zip")
