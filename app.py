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
st.set_page_config(page_title="API 級全量抓取器", page_icon="🔗", layout="wide")
st.title("🔗 API 驅動：族語教材全自動下載優化")

user_id = st.text_input("輸入帳號 (ID)", value="alp11541")

if 'api_units' not in st.session_state:
    st.session_state.api_units = []

if st.button("🚀 從 API 獲取教材清單"):
    with st.spinner("正在呼叫後台 API..."):
        # 你提供的 API 網址
        api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
        
        try:
            res = requests.get(api_url, timeout=15)
            # 偵測回傳格式 (可能是 JSON 或 XML)
            if res.status_code == 200:
                data = res.json() # 假設它是標準 JSON
                
                # --- 自動解析邏輯 ---
                # 這裡會根據回傳的 JSON 結構提取 tid。
                # 假設 JSON 裡面有類似 "tid" 或 "class_id" 的欄位
                found_items = []
                
                # 這是一個遞迴搜尋函數，不管 JSON 有多深，只要看到 tid 就抓
                def find_tids(obj):
                    if isinstance(obj, dict):
                        # 這裡的 key 根據 API 內容調整，常見為 'tid' 或 'id'
                        tid = obj.get('tid') or obj.get('class_id')
                        name = obj.get('title') or obj.get('name') or f"單元 {tid}"
                        if tid:
                            found_items.append({"tid": str(tid), "name": name})
                        for v in obj.values():
                            find_tids(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_tids(item)

                find_tids(data)
                
                # 去重
                unique_items = {i['tid']: i for i in found_items}.values()
                st.session_state.api_units = list(unique_items)
                
                if st.session_state.api_units:
                    st.success(f"✅ 成功！API 回傳了 {len(st.session_state.api_units)} 個單元。")
                else:
                    st.warning("API 連通了，但裡面沒找到單元 ID。請檢查 API 回傳的內容。")
                    st.write("DEBUG (API 內容):", data) # 顯示出來讓我們看結構
            else:
                st.error(f"API 呼叫失敗，狀態碼：{res.status_code}")
        except Exception as e:
            st.error(f"發生錯誤：{e}")

# --- 批次處理 ---
if st.session_state.api_units:
    st.write("---")
    selected_tids = []
    
    cols = st.columns(3)
    for idx, item in enumerate(st.session_state.api_units):
        with cols[idx % 3]:
            if st.checkbox(f"📦 {item['name']} (TID: {item['tid']})", key=f"api_{item['tid']}", value=True):
                selected_tids.append(item)

    if st.button(f"🌀 開始優化下載 ({len(selected_tids)} 個項目)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for i, unit in enumerate(selected_tids):
                st.write(f"正在處理：{unit['name']}")
                dl_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={unit['tid']}"
                try:
                    r = requests.get(dl_url, timeout=20)
                    if len(r.content) > 500:
                        with zipfile.ZipFile(io.BytesIO(r.content)) as sub_zip:
                            for f_name in sub_zip.namelist():
                                if f_name.lower().endswith('.mp3'):
                                    fixed = process_audio_bytes(sub_zip.read(f_name))
                                    master_zip.writestr(f"{unit['tid']}/{os.path.basename(f_name)}", fixed)
                except: pass
                p_bar.progress((i + 1) / len(selected_tids))
        
        st.success("🎉 全部處理完畢！")
        st.download_button("⬇️ 下載 API 優化總包", master_zip_io.getvalue(), "Klokah_API_Fixed.zip")
