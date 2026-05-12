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
st.set_page_config(page_title="第一課全單元抓取", page_icon="🎯")
st.title("🎯 攻克 01梅花般堅強：全單元地毯掃描")

user_id = st.text_input("輸入帳號", value="pic11304")
# 第一課的大標 ID
target_list_id = "17849" 

if st.button("🔍 執行 CSS 穿透掃描"):
    with st.spinner("正在強制提取所有單元按鈕..."):
        url = f"https://web.klokah.tw/text/main.php?user={user_id}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 1. 先找到第一課的大區塊 (使用屬性選擇器)
        # 邏輯：找 data-list="17849" 的按鈕所在的那個 li.list-list
        target_li = None
        all_lis = soup.find_all("li", class_="list-list")
        for li in all_lis:
            if li.find("button", attrs={"data-list": target_list_id}):
                target_li = li
                break
        
        if target_li:
            # 2. 【核心改進】使用 CSS Selector 直接選取所有次單元按鈕
            # 這樣可以避開 BeautifulSoup find_all 在巢狀結構下的限制
            unit_btns = target_li.select("div.list-item button.class-name-btn")
            
            if not unit_btns:
                # 備用方案：如果層級變了，直接抓該區塊內所有 class-name-btn
                unit_btns = target_li.find_all("button", class_="class-name-btn")

            lessons = []
            st.write(f"### 📋 掃描結果 (共找到 {len(unit_btns)} 個單元)")
            
            for b in unit_btns:
                tid = b.get('data-class')
                name = b.get_text(strip=True)
                if tid:
                    st.write(f"✅ 已尋獲：{name} (TID: {tid})")
                    lessons.append({"tid": tid, "name": name})
            
            st.session_state.target_lessons = lessons
            
            if len(lessons) < 6:
                st.warning(f"警告：預期 6 個但只抓到 {len(lessons)} 個，請確認網頁是否已完全展開。")
        else:
            st.error("找不到該課程區塊，請確認第一課的 ID 是否正確。")

# --- 處理與下載 ---
if 'target_lessons' in st.session_state and st.session_state.target_lessons:
    if st.button(f"🚀 開始處理這 {len(st.session_state.target_lessons)} 個單元"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, item in enumerate(st.session_state.target_lessons):
                st.write(f"優化中: {item['name']}")
                zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={item['tid']}"
                try:
                    z_res = requests.get(zip_url, timeout=20)
                    with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                        for f_name in sub_zip.namelist():
                            if f_name.lower().endswith('.mp3'):
                                fixed = process_audio_bytes(sub_zip.read(f_name))
                                # 存入 ZIP
                                master_zip.writestr(f"01_梅花般堅強/{item['tid']}/{os.path.basename(f_name)}", fixed)
                except: pass
                p_bar.progress((idx + 1) / len(st.session_state.target_lessons))
        
        st.success("🎉 處理完成！")
        st.download_button("⬇️ 下載成果", master_zip_io.getvalue(), "Lesson_01_Complete.zip")
