import streamlit as st
import io
import zipfile
import numpy as np
from pydub import AudioSegment
import noisereduce as nr
import librosa
import soundfile as sf
from pydub.silence import detect_nonsilent

# --- 核心音訊後製引擎 (V9.1 安全參數版) ---
def process_audio_post_production(audio_bytes):
    # 1. 載入音檔
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
    
    # 2. 轉為 WAV 格式以進行數位訊號處理
    wav_io = io.BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)
    y, sr = librosa.load(wav_io, sr=None)
    
    # 3. AI 降噪 (針對 130Hz 以上進行處理，降噪比例 0.72)
    # 我們在雲端直接使用 AI 模型進行波形重建
    reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.72, n_fft=2048)
    
    # 4. 回傳至 AudioSegment 進行音量後製
    tmp_io = io.BytesIO()
    sf.write(tmp_io, reduced, sr, format='WAV')
    tmp_io.seek(0)
    audio = AudioSegment.from_wav(tmp_io)
    
    # 5. 精確人聲鎖定 (-48dB 門檻)
    # 找出整段音訊中真正有人說話的地方
    intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
    valid = [i for i in intervals if (i[1] - i[0]) > 100]
    
    if valid:
        # 6. 暴力音量齊平 (-6dB 標靶)
        # 先找到最弱音節，進行動態增益補償
        min_v = min(audio[s:e].dBFS for s, e in valid)
        target_gain = -8.0 - min_v
        audio = audio + max(-2.0, min(target_gain, 15.0))
        
        # 7. 壓限處理 (防止爆音)
        audio = audio.compress_dynamic_range(threshold=-7.0, ratio=8.0, attack=10.0, release=60.0)
        audio = audio + (-6.0 - audio.max_dBFS)
        
        # 8. 安全裁切 (切除開頭與結尾雜音，保留前後各 300ms 緩衝)
        start_p = max(0, valid[0][0] - 300)
        end_p = min(len(audio), valid[-1][1] + 300)
        audio = audio[start_p:end_p]
    
    # 9. 輸出高品質 MP3
    out_io = io.BytesIO()
    audio.export(out_io, format="mp3", bitrate="192k")
    return out_io.getvalue()

# --- Streamlit 網頁介面 ---
st.set_page_config(page_title="族語音訊後製助手", page_icon="✂️")
st.title("✂️ 族語教材：音訊後製與平衡工具")
st.markdown("""
### 操作說明：
1. 上傳從 Klokah 下載的 **原始 ZIP 檔**。
2. 程式會自動進入每個資料夾（如 `74771`）進行後製。
3. 後製完成後，點擊按鈕下載整包優化後的 ZIP。
""")

uploaded_file = st.file_uploader("上傳原始 ZIP 檔案", type="zip")

if uploaded_file is not None:
    if st.button("🚀 開始全自動後製處理"):
        output_zip_io = io.BytesIO()
        
        with zipfile.ZipFile(output_zip_io, 'w', zipfile.ZIP_DEFLATED) as output_zip:
            with zipfile.ZipFile(uploaded_file, 'r') as input_zip:
                # 掃描 ZIP 內所有 MP3 (保留原始目錄層級)
                all_files = [f for f in input_zip.namelist() if f.lower().endswith('.mp3')]
                
                if not all_files:
                    st.error("此 ZIP 內沒有偵測到音訊檔！")
                else:
                    progress_bar = st.progress(0)
                    msg = st.empty()
                    
                    for idx, file_path in enumerate(all_files):
                        msg.text(f"正在後製：{file_path}")
                        
                        with input_zip.open(file_path) as f:
                            # 執行後製核心邏輯
                            processed_data = process_audio_post_production(f.read())
                            # 寫回新 ZIP，路徑維持不變（如 74771/01.mp3）
                            output_zip.writestr(file_path, processed_data)
                            
                        progress_bar.progress((idx + 1) / len(all_files))
                    
                    st.success("✨ 後製完成！已完成所有音量平衡與降噪。")
                    st.download_button(
                        label="⬇️ 下載後製完成包 (ZIP)",
                        data=output_zip_io.getvalue(),
                        file_name=f"Post_Produced_{uploaded_file.name}",
                        mime="application/zip"
                    )