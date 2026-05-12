import streamlit as st
import requests
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
st.set_page_config(page_title="族語教材：全量自動抓取", page_icon="📡", layout="wide")
st.title("📡 穿透掃描：全自動 ZIP 清單提取器")

user_id = st.text_input("輸入帳號 (如: pic11304)", value="pic11304")

if 'found_files' not in st.session_state:
    st.session_state.found_files = []

if st.button("🔍 偵測全網頁可用 ZIP 資源"):
    with st.spinner("正在探測後台資料介面..."):
        # 策略：直接去請求 Klokah 獲取資料清單的 PHP
        # 通常這類動態網頁會有一個讀取清單的 endpoint
        api_url = f"https://web.klokah.tw/text/php/get_text_list.php?user={user_id}" 
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(api_url, headers=headers)
            
            # 如果能拿到 JSON 或 XML 資料
            if res.status_code == 200:
                # 這裡假設它回傳的是結構化資料
                # 若抓不到 API，我們就用「ID 區間暴力探測」
                st.info("正在執行 ID 區間探測 (預測 TID 範圍)...")
                
                # 根據你提供的 74770，我們探測附近 200 個 ID
                start_id = 74770
                results = []
                
                # 建立一個進度條
                p_bar = st.progress(0)
                for i in range(100): # 探測 100 個 ID
                    test_id = start_id + i
                    # 這裡我們不下載整個 ZIP，只用 HEAD 請求確認檔案是否存在
                    check_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={test_id}"
                    check_res = requests.head(check_url)
                    
                    if check_res.status_code == 200:
                        results.append({"tid": str(test_id), "name": f"單元 ID: {test_id}"})
                    
                    p_bar.progress((i + 1) / 100)
                
                st.session_state.found_files = results
                st.success(f"探測完成！發現 {len(results)} 個可下載的 ZIP 資源。")
            else:
                st.error("無法連通後台資料介面。")
        except Exception as e:
            st.error(f"探測發生錯誤：{e}")

# --- 顯示清單與處理 ---
if st.session_state.found_files:
    st.write("---")
    selected_tids = []
    
    cols = st.columns(4)
    for idx, item in enumerate(st.session_state.found_files):
        with cols[idx % 4]:
            if st.checkbox(f"📦 {item['name']}", key=f"chk_{item['tid']}", value=True):
                selected_tids.append(item['tid'])

    if st.button(f"🚀 批次後製下載 ({len(selected_tids)} 個項目)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            proc_bar = st.progress(0)
            for i, tid in enumerate(selected_tids):
                st.write(f"處理中 ID: {tid}...")
                dl_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={tid}"
                r = requests.get(dl_url)
                if len(r.content) > 500:
                    with zipfile.ZipFile(io.BytesIO(r.content)) as sub:
                        for f in sub.namelist():
                            if f.lower().endswith('.mp3'):
                                fixed = process_audio_bytes(sub.read(f))
                                master_zip.writestr(f"{tid}/{os.path.basename(f)}", fixed)
                proc_bar.progress((i + 1) / len(selected_tids))
        
        st.success("✨ 處理完畢！")
        st.download_button("⬇️ 下載優化總包", master_zip_io.getvalue(), "Klokah_Auto_Scan.zip")
