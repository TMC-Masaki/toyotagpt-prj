from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VLM Platform UI</title>

<link
  rel="stylesheet"
  href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<style>
  :root{
    --gap:10px; --pad:10px; --bd:1px solid #ddd; --r:12px;
    --bg:#fff; --panel:#fafafa;
    --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
    --sans: system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  }
  html,body{height:100%;margin:0;font-family:var(--sans);background:var(--bg);}
  .wrap{
    height:100vh;display:grid;
    grid-template-columns:1fr 1fr;
    grid-template-rows:1.55fr 1.45fr;
    gap:var(--gap);padding:var(--pad);box-sizing:border-box;
  }
  .panel{border:var(--bd);border-radius:var(--r);background:var(--panel);overflow:hidden;display:flex;flex-direction:column;min-height:0;}
  .panel h3{margin:0;padding:10px 12px;background:#f2f2f2;border-bottom:var(--bd);font-size:14px;}
  .panel .body{padding:10px 12px;overflow:auto;min-height:0;}

  #pVideo{grid-column:1;grid-row:1;}
  #pCtrl{grid-column:1;grid-row:2;}
  #pMap{grid-column:2;grid-row:1;}
  #pPrompt{grid-column:2;grid-row:2;}
  #pStatus{display:none;}

  #pPrompt{
    grid-column:2;
    grid-row:2;
  }
  #pPrompt .body{
    display:flex;
    flex-direction:column;
    min-height:0;
    height:100%;
  }

  img#video{width:100%;height:100%;object-fit:contain;background:#000;}

  button,select,input{padding:7px 10px;border:var(--bd);border-radius:10px;background:#fff;cursor:pointer;}
  input[type="range"]{width:420px;}
  textarea{width:100%;height:100%;min-height:120px;box-sizing:border-box;padding:10px;border:var(--bd);border-radius:10px;font-family:var(--sans);resize:none;background:#fff;}

  .row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
  .line{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:8px 0;}
  .label{width:92px;color:#555;font-size:12px;}
  .kv{font-family:var(--mono);font-size:12px;}
  .muted{color:#666;font-size:12px;}
  .spacer{flex:1 1 auto;}
  .btn-on{background:#e8fff0;}
  .btn-off{background:#fff3f3;}
  .disabled{opacity:.5; pointer-events:none;}
  .path{width:420px; font-family:var(--mono); font-size:12px;}

  .ctrl-tabs{
    display:flex;
    gap:2px;
    flex-wrap:wrap;
    margin:0 0 12px 0;
    padding:0 0 0 2px;
    border-bottom:var(--bd);
  }
  .ctrl-tab-btn{
    padding:9px 14px 8px 14px;
    border:var(--bd);
    border-bottom:none;
    border-radius:12px 12px 0 0;
    background:#ececec;
    font-size:12px;
    color:#555;
    cursor:pointer;
    margin:0 0 -1px 0;
  }
  .ctrl-tab-btn:hover{
    background:#f3f3f3;
  }
  .ctrl-tab-btn.active{
    background:var(--panel);
    color:#111;
    font-weight:700;
    position:relative;
    z-index:2;
  }
  .ctrl-tab-panel{
    display:none;
    padding-top:2px;
  }
  .ctrl-tab-panel.active{
    display:block;
  }

  .monitor-tabs{
    display:flex;
    gap:2px;
    flex-wrap:wrap;
    margin:0 0 12px 0;
    padding:0 0 0 2px;
    border-bottom:var(--bd);
  }
  .monitor-tab-btn{
    padding:9px 14px 8px 14px;
    border:var(--bd);
    border-bottom:none;
    border-radius:12px 12px 0 0;
    background:#ececec;
    font-size:12px;
    color:#555;
    cursor:pointer;
    margin:0 0 -1px 0;
  }
  .monitor-tab-btn:hover{
    background:#f3f3f3;
  }
  .monitor-tab-btn.active{
    background:var(--panel);
    color:#111;
    font-weight:700;
    position:relative;
    z-index:2;
  }
  .monitor-tab-panel{
    display:none;
    min-height:0;
    height:100%;
    padding-top:2px;
  }
  .monitor-tab-panel.active{
    display:block;
  }

  .placeholder{
    background:#fff;
    border:var(--bd);
    border-radius:10px;
    padding:14px;
    color:#555;
    font-size:12px;
    line-height:1.6;
  }

  /* status table */
  table.status{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;background:#fff;border:var(--bd);border-radius:10px;overflow:hidden;}
  table.status td{padding:8px 10px;border-bottom:var(--bd);vertical-align:top;}
  table.status tr:last-child td{border-bottom:none;}
  td.k{width:140px;color:#555;background:#fafafa;}
  td.v{white-space:pre-wrap;word-break:break-word;}
  .pill{display:inline-block;padding:2px 8px;border:var(--bd);border-radius:999px;background:#fff;font-family:var(--mono);font-size:12px;}
  .pill.on{background:#e8fff0;}
  .pill.off{background:#fff3f3;}

  #map{width:100%;height:100%;min-height:200px;background:#eaeaea;}
  #mapHint{position:absolute;top:10px;left:10px;z-index:999;background:rgba(255,255,255,0.9);border:var(--bd);border-radius:10px;padding:6px 10px;font-family:var(--mono);font-size:12px;}
  #mapWrap{position:relative;flex:1 1 auto;min-height:0;}
/* Map */
#pMap .body{
  padding:0 !important;
  overflow:hidden !important;      /* auto だと高さ計算が崩れやすい */
  display:flex;
  flex-direction:column;
  height:100%;
  min-height:0;
}
#mapWrap{
  position:relative;
  flex:1 1 auto;
  min-height:0;
}
#map{
  width:100%;
  height:100%;
  min-height:200px;
  background:#eaeaea;
}
#mapHint{
  position:absolute;
  top:10px;
  left:10px;
  z-index:999;
  background:rgba(255,255,255,0.9);
  border:var(--bd);
  border-radius:10px;
  padding:6px 10px;
  font-family:var(--mono);
  font-size:12px;
}
</style>
</head>

<body>
<div class="wrap">

<section id="pVideo" class="panel">
  <h3>映像</h3>
  <div class="body" style="padding:0;">
    <img id="video" src="/stream.mjpeg?fps=5" alt="video">
  </div>
</section>

<section id="pCtrl" class="panel">
  <h3>操作・設定</h3>
  <div class="body">
    <div class="ctrl-tabs">
      <button type="button" class="ctrl-tab-btn active" data-ctrl-tab="output">出力設定</button>
      <button type="button" class="ctrl-tab-btn" data-ctrl-tab="can">CAN</button>
      <button type="button" class="ctrl-tab-btn" data-ctrl-tab="yolo">YOLO</button>
      <button type="button" class="ctrl-tab-btn" data-ctrl-tab="vlm">VLM</button>
    </div>

    <div id="ctrl-panel-output" class="ctrl-tab-panel active">
      <div class="line">
        <button id="btnStart">推論開始</button>
        <button id="btnStop">推論停止</button>
        <span class="kv">Status: <b id="sch">?</b></span>

        <button id="btnUploadToggle" class="btn-off">AWS Upload ?</button>
        <span class="kv">Status: <b id="uploadStateText">?</b></span>

        <span class="spacer"></span>
        <button id="btnSpeech" class="btn-off">音声OFF</button>
        <button id="btnSpeakTest">音声テスト</button>
      </div>

      <div class="line">
        <div class="label">入力設定</div>
        <select id="inputType">
          <option value="camera">Camera</option>
          <option value="video_file">動画ファイル</option>
          <option value="image_dir">画像列フォルダ</option>
        </select>
        <input id="inputPath" class="path" placeholder="/data/sample.mp4 など（コンテナ内パス）">
        <button id="btnApplyInput">適用</button>
      </div>

      <div class="line">
        <div class="label">動画位置</div>
        <input id="seek" type="range" min="0" max="0" step="1" value="0">
        <span class="kv">pos <b id="seekPos">0.0</b>s / <b id="seekDur">0.0</b>s</span>
      </div>

      <div class="line">
        <div class="label">Overlay</div>
        <label><input id="overlayEnabled" type="checkbox" checked> Overlay描画を有効</label>
      </div>

      <div class="line">
        <div class="label">評価ログ</div>
        <label><input id="evalLogEnabled" type="checkbox" checked> 評価ログを有効</label>
      </div>

      <div class="line">
        <div class="label">保存先</div>
        <input id="saveDir" class="path" value="/mnt/vlm_data/logs/events">
        <span class="spacer"></span>
        <button id="btnSave">設定保存</button>
        <span id="saveMsg" class="muted"></span>
      </div>
    </div>

    <div id="ctrl-panel-can" class="ctrl-tab-panel">
      <div class="line">
        <div class="label">CAN Mode</div>
        <select id="canMode">
          <option value="disabled">disabled</option>
          <option value="dummy">dummy</option>
          <option value="real">real</option>
        </select>
      </div>

      <div class="line">
        <div class="label">CAN Dummy Speed</div>
        <input id="canDummyVehicleSpeed" type="number" step="0.1" style="width:90px;">
        <span class="kv">km/h</span>
      </div>

      <div class="line">
        <div class="label">CAN Dummy Shift</div>
        <select id="canDummyShift">
          <option value="P">P</option>
          <option value="R">R</option>
          <option value="N">N</option>
          <option value="D">D</option>
          <option value="B">B</option>
        </select>
      </div>

      <div class="line">
        <div class="label">CAN Dummy Accel XYZ</div>
        <input id="canDummyAccelX" type="number" step="0.01" style="width:90px;">
        <input id="canDummyAccelY" type="number" step="0.01" style="width:90px;">
        <input id="canDummyAccelZ" type="number" step="0.01" style="width:90px;">
      </div>

      <div class="line">
        <div class="label">CAN Dummy Pedal</div>
        <input id="canDummyPedalAccel" type="number" step="0.1" style="width:90px;">
        <span class="kv">Accel</span>
        <input id="canDummyPedalBrake" type="number" step="0.1" style="width:90px;">
        <span class="kv">Brake</span>
      </div>

      <div class="line">
        <div class="label">CAN Dummy Steering</div>
        <input id="canDummySteeringRate" type="number" step="0.1" style="width:90px;">
        <span class="kv">deg/s</span>
      </div>
    </div>

    <div id="ctrl-panel-yolo" class="ctrl-tab-panel">
      <div class="line">
        <div class="label">YOLO</div>
        <button id="btnYolo" class="btn-off">OFF</button>
        <select id="yoloModel">
          <option value="yolov8n.pt">yolov8n</option>
          <option value="yolov8s.pt">yolov8s</option>
          <option value="yolov8m.pt">yolov8m</option>
        </select>
      </div>

      <div class="line">
        <div class="label">conf</div>
        <input id="yoloConf" type="range" min="0.05" max="0.90" step="0.05" value="0.25">
        <span class="kv"><b id="yoloConfVal">0.25</b></span>
      </div>

      <div class="line">
        <div class="label">YOLO周期(Hz)</div>
        <input id="yoloPreviewHz" type="range" min="0.5" max="10.0" step="0.5" value="3.0">
        <span class="kv"><b id="yoloPreviewHzVal">3.0</b> Hz</span>
      </div>

      <div class="line">
        <div class="label">Risk: Scene</div>
        <button type="button" id="riskSceneWeightDec">-</button>
        <input id="riskSceneWeight" type="number" min="0.00" max="1.00" step="0.01" value="0.35" style="width:90px;">
        <button type="button" id="riskSceneWeightInc">+</button>
      </div>

      <div class="line">
        <div class="label">Risk: VRU</div>
        <button type="button" id="riskVruWeightDec">-</button>
        <input id="riskVruWeight" type="number" min="0.00" max="1.00" step="0.01" value="0.25" style="width:90px;">
        <button type="button" id="riskVruWeightInc">+</button>
      </div>

      <div class="line">
        <div class="label">Risk: Blindspot</div>
        <button type="button" id="riskBlindspotWeightDec">-</button>
        <input id="riskBlindspotWeight" type="number" min="0.00" max="1.00" step="0.01" value="0.20" style="width:90px;">
        <button type="button" id="riskBlindspotWeightInc">+</button>
      </div>

      <div class="line">
        <div class="label">Risk: SpeedMismatch</div>
        <button type="button" id="riskSpeedMismatchWeightDec">-</button>
        <input id="riskSpeedMismatchWeight" type="number" min="0.00" max="1.00" step="0.01" value="0.20" style="width:90px;">
        <button type="button" id="riskSpeedMismatchWeightInc">+</button>
      </div>

      <div class="line">
        <div class="label">Risk: MID threshold</div>
        <button type="button" id="riskMidThresholdDec">-</button>
        <input id="riskMidThreshold" type="number" min="0.00" max="100.00" step="0.01" value="35.00" style="width:90px;">
        <button type="button" id="riskMidThresholdInc">+</button>
      </div>

      <div class="line">
        <div class="label">Risk: HIGH threshold</div>
        <button type="button" id="riskHighThresholdDec">-</button>
        <input id="riskHighThreshold" type="number" min="0.00" max="100.00" step="0.01" value="55.00" style="width:90px;">
        <button type="button" id="riskHighThresholdInc">+</button>
      </div>
    </div>

    <div id="ctrl-panel-vlm" class="ctrl-tab-panel">
      <div class="line">
        <div class="label">VLM</div>
        <button id="btnVlm" class="btn-on" data-enabled="1">ON</button>
      </div>

      <div class="line">
        <div class="label">1次推論モデル</div>
        <select id="preset" style="width:520px;">
          <option value="llava15_7b_hf">LLaVA 1.5 7B (HF/GPU)</option>
          <option value="llava15_13b_hf">LLaVA 1.5 13B (HF/GPU)</option>
          <option value="llava_ov_05b_hf">LLaVA-OneVision 0.5B (HF/GPU)</option>
          <option value="llava_ov_7b_hf">LLaVA-OneVision 7B (HF/GPU)</option>
          <option value="qwen2vl_2b_hf">Qwen2-VL 2B (HF/GPU)</option>
          <option value="qwen2vl_7b_hf">Qwen2-VL 7B (HF/GPU)</option>
          <option value="qwen25_3b_hf">Qwen2.5-VL 3B (HF/GPU)</option>
          <option value="qwen25_7b_hf">Qwen2.5-VL 7B (HF/GPU)</option>
          <option value="smolvlm_hf">SmolVLM Instruct (HF/GPU)</option>
        </select>
      </div>

      <div class="line">
        <div class="label">2次推論モデル</div>
        <select id="presetSecondary" style="width:520px;" disabled>
          <option value="">未接続（UIプレースホルダ）</option>
        </select>
      </div>

      <div class="line">
        <div class="label">推論周期</div>
        <input id="interval" type="range" min="0.1" max="20.0" step="0.1" value="2.0">
        <span class="kv"><b id="intervalVal">2.0</b>s</span>
      </div>

      <div class="line">
        <div class="label">VLM周期</div>
        <input id="vlmInterval" type="range" min="0.2" max="60.0" step="0.2" value="2.0">
        <span class="kv"><b id="vlmIntervalVal">2.0</b>s</span>
      </div>
    </div>
  </div>
</section>

<section id="pMap" class="panel">
  <h3>Map（GNSS）</h3>
  <div class="body" style="padding:0;">
    <div id="mapWrap">
      <div id="mapHint">GNSS: waiting…（未接続）</div>
      <div id="map"></div>
    </div>
  </div>
</section>

<section id="pPrompt" class="panel">
  <h3>プロンプト / 状態監視</h3>
  <div class="body">
    <div class="monitor-tabs">
      <button type="button" class="monitor-tab-btn active" data-monitor-tab="primary">1次推論</button>
      <button type="button" class="monitor-tab-btn" data-monitor-tab="secondary">2次推論</button>
      <button type="button" class="monitor-tab-btn" data-monitor-tab="primary_input">1次VLM Input</button>
      <button type="button" class="monitor-tab-btn" data-monitor-tab="secondary_input">2次VLM Input</button>
      <button type="button" class="monitor-tab-btn" data-monitor-tab="status">内部状態・出力</button>
    </div>

    <div id="monitor-panel-primary" class="monitor-tab-panel active">
      <div class="row" style="margin-bottom:8px; gap:12px; flex-wrap:wrap;">
        <button id="btnApplyPrompt">プロンプト適用</button>
        <label><input type="radio" name="promptUpdateMode" id="promptModeManual" value="manual" checked> 手動</label>
        <label><input type="radio" name="promptUpdateMode" id="promptModeAuto" value="auto"> 自動更新</label>
        <button id="applyVlmPromptTemplateBtn" type="button">VLMテンプレート適用</button>
        <span class="muted">自動更新時は車速・進行方向・YOLO検出物を差し込み / Enter単体は改行</span>
      </div>
      <textarea id="prompt"></textarea>
    </div>

    <div id="monitor-panel-secondary" class="monitor-tab-panel">
      <div class="placeholder">
        <b>2次推論タブ</b><br><br>
        現在のUI / JSでは 1次推論 prompt のみ接続されています。<br>
        このタブはレイアウト先行で追加しています。<br>
        2次推論モデル・2次推論プロンプト・保存先 API は後で接続します。
      </div>
    </div>

    <div id="monitor-panel-primary_input" class="monitor-tab-panel">
      <div class="row" style="margin-bottom:8px;"><b>1次推論 VLM Input</b></div>
      <pre id="st_vlm_input" style="white-space:pre-wrap; word-break:break-word; margin:0; max-height:420px; overflow:auto;"></pre>
    </div>

    <div id="monitor-panel-secondary_input" class="monitor-tab-panel">
      <div class="row" style="margin-bottom:8px;"><b>2次推論 VLM Input</b></div>
      <pre id="st_secondary_input" style="white-space:pre-wrap; word-break:break-word; margin:0; max-height:420px; overflow:auto;"></pre>
    </div>

    <div id="monitor-panel-status" class="monitor-tab-panel">
      <table class="status">
        <tr><td class="k">映像</td><td class="v" id="st_source">-</td></tr>
        <tr><td class="k">表示</td><td class="v" id="st_display">-</td></tr>
        <tr><td class="k">Voice</td><td class="v" id="st_voice">-</td></tr>
        <tr><td class="k">Speech API</td><td class="v" id="st_speech_api">-</td></tr>
        <tr><td class="k">Speech Voices</td><td class="v" id="st_speech_voices">-</td></tr>
        <tr><td class="k">Speech Last Error</td><td class="v" id="st_speech_error">-</td></tr>
        <tr><td class="k">API Time</td><td class="v" id="st_api_time">0.0s</td></tr>

        <tr><td class="k">VLM</td><td class="v" id="st_vlm_model">-</td></tr>
        <tr><td class="k">VLM Enabled</td><td class="v" id="st_vlm_enabled">-</td></tr>
        <tr><td class="k">VLM Engine</td><td class="v" id="st_vlm_engine">-</td></tr>
        <tr><td class="k">VLM Emit Interval</td><td class="v" id="st_vlm_emit_interval_sec">-</td></tr>
        <tr><td class="k">VLM Busy</td><td class="v" id="st_vlm_busy">-</td></tr>
        <tr><td class="k">VLM Running</td><td class="v" id="st_vlm_running">-</td></tr>
        <tr><td class="k">VLM Status</td><td class="v" id="st_vlm_status">0</td></tr>
        <tr><td class="k">VLM Output</td><td class="v" id="st_vlm_output"></td></tr>
        <tr><td class="k">VLM Latency</td><td class="v" id="st_vlm_latency_ms">-</td></tr>
        <tr><td class="k">Risk</td><td class="v" id="st_risk_level">-</td></tr>
        <tr><td class="k">Risk Score</td><td class="v" id="st_risk_score">-</td></tr>
        <tr><td class="k">Risk Reason</td><td class="v" id="st_risk_reason">-</td></tr>
        <tr><td class="k">Speak Policy</td><td class="v" id="st_speak_policy">-</td></tr>
        <tr><td class="k">Scene Complexity</td><td class="v" id="st_scene_complexity">-</td></tr>
        <tr><td class="k">VRU Load</td><td class="v" id="st_vru_load">-</td></tr>
        <tr><td class="k">Blindspot/Predictive</td><td class="v" id="st_blindspot_load">-</td></tr>
        <tr><td class="k">Speed Mismatch</td><td class="v" id="st_speed_mismatch">-</td></tr>
        <tr><td class="k">Event Type</td><td class="v" id="st_event_type">-</td></tr>
        <tr><td class="k">Event Info</td><td class="v" id="st_event_info">-</td></tr>

        <tr><td class="k">YOLO</td><td class="v" id="st_yolo_model">-</td></tr>
        <tr><td class="k">YOLO Status</td><td class="v" id="st_yolo_status">0</td></tr>
        <tr><td class="k">YOLO FPS</td><td class="v" id="st_yolo_fps">-</td></tr>
        <tr><td class="k">YOLO Latency</td><td class="v" id="st_yolo_latency_ms">-</td></tr>
        <tr><td class="k">YOLO Detect</td><td class="v" id="st_yolo_detect"></td></tr>
        <tr><td class="k">GNSS</td><td class="v" id="st_gnss_status">-</td></tr>
        <tr><td class="k">GNSS LatLon</td><td class="v" id="st_gnss_latlon">-</td></tr>

        <tr><td class="k">Upload Enabled</td><td class="v" id="st_upload_enabled">-</td></tr>
        <tr><td class="k">Upload Mode</td><td class="v" id="st_upload_mode">-</td></tr>
        <tr><td class="k">Upload Bucket</td><td class="v" id="st_upload_bucket">-</td></tr>
        <tr><td class="k">Upload Table</td><td class="v" id="st_upload_table">-</td></tr>

        <tr><td class="k">CAN状態</td><td class="v" id="st_can_status">-</td></tr>
        <tr><td class="k">車速</td><td class="v" id="st_can_speed">-</td></tr>
        <tr><td class="k">シフト</td><td class="v" id="st_can_shift">-</td></tr>
        <tr><td class="k">前後G / 加速度</td><td class="v" id="st_can_accel">-</td></tr>
        <tr><td class="k">ペダル</td><td class="v" id="st_can_pedal">-</td></tr>
        <tr><td class="k">ステア</td><td class="v" id="st_can_steering_rate">-</td></tr>
        <tr><td class="k">CAN信号数</td><td class="v" id="st_can_signal_count">-</td></tr>
        <tr><td class="k">CAN信号詳細</td><td class="v" id="st_can_signal_summary">-</td></tr>
      </table>
      <div class="kv muted" id="err" style="margin-top:8px;"></div>
    </div>
  </div>
</section>

<section id="pStatus" class="panel" style="display:none;">
  <h3>内部状態 / 出力</h3>
  <div class="body"></div>
</section>

</div>

<script>
const api = (path, opts={}) => fetch(path, opts).then(r => r.json());

const PRESET = {
  llava15_7b_hf:   { vlm_engine: "hf", vlm_model_name: "llava-hf/llava-1.5-7b-hf" },
  llava15_13b_hf:  { vlm_engine: "hf", vlm_model_name: "llava-hf/llava-1.5-13b-hf" },
  llava_ov_05b_hf: { vlm_engine: "hf", vlm_model_name: "llava-hf/llava-onevision-qwen2-0.5b-ov-hf" },
  llava_ov_7b_hf:  { vlm_engine: "hf", vlm_model_name: "llava-hf/llava-onevision-qwen2-7b-ov-hf" },

  qwen2vl_2b_hf:   { vlm_engine: "hf", vlm_model_name: "Qwen/Qwen2-VL-2B-Instruct" },
  qwen2vl_7b_hf:   { vlm_engine: "hf", vlm_model_name: "Qwen/Qwen2-VL-7B-Instruct" },
  qwen25_3b_hf:    { vlm_engine: "hf", vlm_model_name: "Qwen/Qwen2.5-VL-3B-Instruct" },
  qwen25_7b_hf:    { vlm_engine: "hf", vlm_model_name: "Qwen/Qwen2.5-VL-7B-Instruct" },

  smolvlm_hf:      { vlm_engine: "hf", vlm_model_name: "HuggingFaceTB/SmolVLM-Instruct" },
};

let speechEnabled = false;
let speechAvailable = false;
let speechVoicesCount = 0;
let speechLastError = "";
let yoloEnabled = false;
let dirty = false;
let promptDirty = false;
let promptFocused = false;
let seekDirty = false;
let seeking = false;
let videoRunning = null;
let lastSpoken = "";
let lastSpokenAtMs = 0;
let speechManualUntilMs = 0;
let speechNowSource = "";
let lastAutoSpokenFrameId = -1;
let autoSpeakCooldownMs = 8000;

function getSpeechVoicesSafe(){
  try{
    if(!window.speechSynthesis) return [];
    return speechSynthesis.getVoices() || [];
  }catch(e){
    speechLastError = "getVoices error: " + String(e);
    return [];
  }
}

function pickJapaneseVoice(voices){
  const vs = Array.isArray(voices) ? voices : [];
  return (
    vs.find(v => /^ja(-|_)?/i.test(String(v.lang || ""))) ||
    vs.find(v => /japanese|japan|ja/i.test(String(v.name || ""))) ||
    vs[0] ||
    null
  );
}

async function speakText(t){
  const el = document.getElementById("err");
  try{
    speechLastError = "server speak request";
    if(el) el.textContent = speechLastError;
    const r = await fetch("/speech/speak", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({text: String(t || "")})
    });
    const j = await r.json();
    speechLastError = j.ok ? "server speak ok" : ("server speak error: " + String(j.error || "unknown"));
    if(el) el.textContent = speechLastError;
  }catch(e){
    speechLastError = "server speak exception: " + String(e);
    if(el) el.textContent = speechLastError;
  }
}

function unlockSpeech(){
  try{
    if(!window.speechSynthesis){
      speechAvailable = false;
      speechLastError = "speechSynthesis unavailable";
      const el = document.getElementById("err");
      if(el) el.textContent = speechLastError;
      return;
    }

    speechAvailable = true;
    const u = new SpeechSynthesisUtterance("");
    u.volume = 0;
    u.rate = 1.0;
    u.pitch = 1.0;
    try{ speechSynthesis.resume(); }catch(e){}
    speechSynthesis.speak(u);

    setTimeout(()=>{
      try{ speechSynthesis.cancel(); }catch(e){}
    }, 50);

    speechLastError = "speech unlocked";
    const el = document.getElementById("err");
    if(el) el.textContent = speechLastError;
  }catch(e){
    speechLastError = "unlock error: " + String(e);
    const el = document.getElementById("err");
    if(el) el.textContent = speechLastError;
  }
}
try{
  if(window.speechSynthesis){
    window.speechSynthesis.onvoiceschanged = () => {
      try{
        speechVoicesCount = (speechSynthesis.getVoices() || []).length;
      }catch(e){
        speechLastError = "voiceschanged error: " + String(e);
        const el = document.getElementById("err");
        if(el) el.textContent = speechLastError;
      }
    };
  }
}catch(e){
  speechLastError = "speech init error: " + String(e);
  const el = document.getElementById("err");
  if(el) el.textContent = speechLastError;
}

window.onerror = function(message, source, lineno, colno, error){
  speechLastError = "js error: " + String(message) + " @ " + String(lineno) + ":" + String(colno);
  const el = document.getElementById("err");
  if(el) el.textContent = speechLastError;
};

window.onunhandledrejection = function(event){
  speechLastError = "promise error: " + String((event && event.reason) ? event.reason : event);
  const el = document.getElementById("err");
  if(el) el.textContent = speechLastError;
};

function setSpeechBtn(){
  const b = document.getElementById("btnSpeech");
  if(speechEnabled){ b.textContent="音声ON"; b.classList.add("btn-on"); b.classList.remove("btn-off"); }
  else { b.textContent="音声OFF"; b.classList.add("btn-off"); b.classList.remove("btn-on"); }
}
function setYoloBtn(){
  const b = document.getElementById("btnYolo");
  if(yoloEnabled){ b.textContent="ON"; b.classList.add("btn-on"); b.classList.remove("btn-off"); }
  else { b.textContent="OFF"; b.classList.add("btn-off"); b.classList.remove("btn-on"); }
}

async function applyConfig(body){
  return await api("/config", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
}

async function setUploadEnabled(enabled){
  try{
    await applyConfig({upload_enabled: !!enabled});
    await refreshAll();
  }catch(e){
    const el = document.getElementById("err");
    if(el) el.textContent = "upload toggle error: " + String(e);
  }
}

async function waitSchedulerRunning(timeoutMs=3000){
  const t0 = Date.now();
  while((Date.now() - t0) < timeoutMs){
    try{
      const sch = await api("/scheduler/status");
      if(sch && sch.running) return true;
    }catch(e){}
    await new Promise(r => setTimeout(r, 150));
  }
  return false;
}

function setVideoRunning(running){
  if(videoRunning === running) return;
  videoRunning = running;
  const img = document.getElementById("video");
  if(running){
    if(img.getAttribute("src") !== "/stream.mjpeg?fps=5") img.setAttribute("src","/stream.mjpeg?fps=5");
  }else{
    img.setAttribute("src","/frame.jpg");
  }
}

function updateSeekEnabled(){
  const typ = document.getElementById("inputType").value;
  const seek = document.getElementById("seek");
  if(typ === "camera"){
    seek.classList.add("disabled");
  }else{
    seek.classList.remove("disabled");
  }
}

async function refreshVideoStatus(){
  try{
    const typ = document.getElementById("inputType").value;
    if(typ === "camera"){
      document.getElementById("seekPos").textContent = "0.0";
      document.getElementById("seekDur").textContent = "0.0";
      return;
    }
    const vs = await api("/video/status");
    if(vs && vs.ok){
      document.getElementById("seekPos").textContent = (vs.pos_sec||0).toFixed(1);
      document.getElementById("seekDur").textContent = (vs.duration_sec||0).toFixed(1);

      const dur = Math.max(0, Number(vs.duration_sec||0));
      const pos = Math.max(0, Number(vs.pos_sec||0));
      const seek = document.getElementById("seek");

      seek.max = String(Math.floor(dur));
      seek.step = "1";

      if(!seeking && !seekDirty && !dirty){
        seek.value = String(Math.floor(pos));
      }
    }
  }catch(e){}
}

function setStatusUI(st){
  document.getElementById("st_source").textContent = st?.source ?? "-";
  document.getElementById("st_display").textContent = st?.display ?? "-";
  document.getElementById("st_voice").textContent = st?.voice ?? "-";

  speechAvailable = !!window.speechSynthesis;
  try{
    speechVoicesCount = speechAvailable ? (speechSynthesis.getVoices() || []).length : 0;
  }catch(e){
    speechVoicesCount = -1;
    speechLastError = "voices error: " + String(e);
  }

  document.getElementById("st_speech_api").textContent =
    speechAvailable ? "available" : "unavailable";
  document.getElementById("st_speech_voices").textContent = String(speechVoicesCount);
  document.getElementById("st_speech_error").textContent = speechLastError || "-";

  const t = Number(st?.api_time_sec ?? 0);
  document.getElementById("st_api_time").textContent = (isFinite(t)? t.toFixed(1):"0.0") + "s";

  document.getElementById("st_vlm_model").textContent = st?.vlm_model ?? "-";
  document.getElementById("st_vlm_enabled").textContent =
    (st?.vlm_enabled == null) ? "-" : String(st.vlm_enabled);
  document.getElementById("st_vlm_engine").textContent = st?.vlm_engine ?? "-";
  document.getElementById("st_vlm_emit_interval_sec").textContent =
    (st?.vlm_emit_interval_sec == null) ? "-" : String(st.vlm_emit_interval_sec) + " s";
  document.getElementById("st_vlm_busy").textContent =
    (st?.vlm_busy == null) ? "-" : String(st.vlm_busy);
  document.getElementById("st_vlm_running").textContent =
    (st?.vlm_running == null) ? "-" : String(st.vlm_running);
  document.getElementById("st_vlm_status").textContent = String(st?.vlm_status ?? 0);
  document.getElementById("st_vlm_input").textContent = st?.vlm_input ?? "";
  document.getElementById("st_secondary_input").textContent = st?.secondary_input ?? "-";
  document.getElementById("st_vlm_output").textContent = st?.vlm_output ?? "";
  document.getElementById("st_vlm_latency_ms").textContent =
    (st?.vlm_latency_ms == null) ? "-" : String(st.vlm_latency_ms) + " ms";
  document.getElementById("st_risk_level").textContent = st?.risk_level ?? "-";
  document.getElementById("st_risk_score").textContent = String(st?.risk_score ?? "-");
  document.getElementById("st_risk_reason").textContent =
    String(st?.risk_reason ?? "-")
    + " / w=("
    + String(st?.risk_scene_complexity_weight ?? "-") + ", "
    + String(st?.risk_vru_weight ?? "-") + ", "
    + String(st?.risk_blindspot_weight ?? "-") + ", "
    + String(st?.risk_speed_mismatch_weight ?? "-") + ")"
    + " / th=("
    + String(st?.risk_mid_threshold ?? "-") + ", "
    + String(st?.risk_high_threshold ?? "-") + ")";
  document.getElementById("st_speak_policy").textContent =
    "interval=" + String(st?.speak_interval_sec ?? "-") + "s";
  document.getElementById("st_scene_complexity").textContent = String(st?.scene_complexity ?? "-");
  document.getElementById("st_vru_load").textContent = String(st?.vru_load ?? "-");
  document.getElementById("st_blindspot_load").textContent = String(st?.blindspot_predictive_load ?? "-");
  document.getElementById("st_speed_mismatch").textContent = String(st?.speed_mismatch ?? "-");

  document.getElementById("st_event_type").textContent = String(st?.event_type ?? "-");
  document.getElementById("st_event_info").textContent =
    "conf=" + String(st?.event_confidence ?? "-")
    + " / reason=" + String(st?.event_reason ?? "-");

  document.getElementById("st_yolo_model").textContent = st?.yolo_model ?? "-";
  document.getElementById("st_yolo_status").textContent = String(st?.yolo_status ?? 0);
  document.getElementById("st_yolo_fps").textContent =
    (st?.yolo_fps == null) ? "-" : String(st.yolo_fps);
  document.getElementById("st_yolo_latency_ms").textContent =
    (st?.yolo_latency_ms == null) ? "-" : String(st.yolo_latency_ms) + " ms";

  const yoloOut = (typeof st?.yolo_output === "string" && st.yolo_output.length > 0)
    ? st.yolo_output
    : ((Array.isArray(st?.yolo_detect) ? st.yolo_detect : []).join(", "));
  document.getElementById("st_yolo_detect").textContent = yoloOut;

  document.getElementById("st_gnss_status").textContent = st?.gnss_status ?? "-";
  const uploadEnabled = !!st?.upload_enabled;
  const uploadMode = String(st?.upload_mode ?? "-");
  const uploadBucket = String(st?.upload_bucket ?? "-");
  const uploadTable = String(st?.upload_table ?? "-");

  const uploadStateText = document.getElementById("uploadStateText");
  if(uploadStateText){
    uploadStateText.textContent = uploadEnabled ? (uploadMode.toUpperCase() + " ON") : (uploadMode.toUpperCase() + " OFF");
  }

  const btnUploadToggle = document.getElementById("btnUploadToggle");
  if(btnUploadToggle){
    btnUploadToggle.textContent = uploadEnabled ? "AWS Upload OFF" : "AWS Upload ON";
    btnUploadToggle.classList.toggle("btn-on", !uploadEnabled);
    btnUploadToggle.classList.toggle("btn-off", uploadEnabled);
  }

  const stUploadEnabled = document.getElementById("st_upload_enabled");
  if(stUploadEnabled) stUploadEnabled.textContent = String(uploadEnabled);
  const stUploadMode = document.getElementById("st_upload_mode");
  if(stUploadMode) stUploadMode.textContent = uploadMode;
  const stUploadBucket = document.getElementById("st_upload_bucket");
  if(stUploadBucket) stUploadBucket.textContent = uploadBucket;
  const stUploadTable = document.getElementById("st_upload_table");
  if(stUploadTable) stUploadTable.textContent = uploadTable;

  document.getElementById("st_gnss_status").textContent = st?.gnss_status ?? "-";
  let gnssLine = st?.gnss_latlon ?? "-";
  if(st?.gnss_last_ts){
    gnssLine += "\nlast_ts=" + String(st.gnss_last_ts);
  }
  if(st?.gnss_error){
    gnssLine += "\nerr=" + String(st.gnss_error);
  }
  document.getElementById("st_gnss_latlon").textContent = gnssLine;

  let canLine = st?.can_status ?? "-";
  if(st?.can_last_ts){
    canLine += "\nlast_ts=" + String(st.can_last_ts);
  }
  if(st?.can_error){
    canLine += "\nerr=" + String(st.can_error);
  }
  document.getElementById("st_can_status").textContent = canLine;
  document.getElementById("st_can_speed").textContent = st?.can_speed ?? "-";
  document.getElementById("st_can_shift").textContent = st?.can_shift ?? "-";
  document.getElementById("st_can_accel").textContent = st?.can_accel ?? "-";
  document.getElementById("st_can_pedal").textContent = st?.can_pedal ?? "-";
  document.getElementById("st_can_steering_rate").textContent = st?.can_steering_rate ?? "-";
  document.getElementById("st_can_signal_count").textContent = String(st?.can_signal_count ?? "-");
  document.getElementById("st_can_signal_summary").textContent = st?.can_signal_summary ?? "-";

  // auto speak with fixed rule-based text
  try{
    const now = Date.now();
    const voiceOn = String(st?.voice ?? "") === "ON";
    const speechText = String(st?.speech_text ?? "").trim();
    const speechKey = String(st?.speech_key ?? "").trim();
    const repeatSecRaw = Number(st?.speech_repeat_sec ?? 0);
    const repeatMs = repeatSecRaw > 0 ? (repeatSecRaw * 1000) : autoSpeakCooldownMs;
    const speakingNow = false;
    const sameKey = !!(window.__lastAutoSpeechKey && speechKey && window.__lastAutoSpeechKey === speechKey);
    const cooldownPassed = (now - lastSpokenAtMs) >= repeatMs;
    const canSpeakOnce = !!speechText && !!speechKey && !sameKey;
    const canSpeakRepeat = !!speechText && !!speechKey && sameKey && repeatSecRaw > 0 && cooldownPassed;

    if(
      voiceOn &&
      speechText &&
      now >= speechManualUntilMs &&
      !speakingNow &&
      (canSpeakOnce || canSpeakRepeat)
    ){
      speechNowSource = "auto";
      window.__lastAutoSpeechKey = speechKey;
      lastSpoken = speechText;
      lastSpokenAtMs = now;
      speakText(speechText);
    }
  }catch(e){
    speechLastError = "auto speak error: " + String(e);
    const el = document.getElementById("err");
    if(el) el.textContent = speechLastError;
  }
}

function setVlmBtn(enabled){
  const b = document.getElementById("btnVlm");
  if(!b) return;
  b.dataset.enabled = enabled ? "1" : "0";
  b.textContent = enabled ? "ON" : "OFF";
  b.className = enabled ? "btn-on" : "btn-off";
}


function promptAutoEnabled(){
  return !!document.getElementById("promptModeAuto")?.checked;
}

function buildHighComplexPrompt(speedText, shiftText, yoloText){
  return `目的：
現在シーンから、共有価値のあるイベント候補を抽出する。

入力内容：
現在の車速：${speedText}
進行方向：${shiftText}
YOLO検出物【検出数】：${yoloText}

検出して欲しいもの：
以下の Event 候補の中から、該当するものを 0〜3 件選ぶこと。
Event 名は必ず以下のキーをそのまま使うこと。

EVENT_RULES = [
("road_depression", [
"陥没", "穴", "路面損傷", "路面の穴", "道路陥没"
]),
("fallen_object", [
"落下物", "障害物", "路上障害物", "散乱物", "荷物"
]),
("road_work", [
"工事", "工事中", "車線規制", "規制", "コーン", "ポール"
]),
("traffic_jam", [
"渋滞", "混雑", "車列", "停滞", "流れが悪い"
]),
("accident", [
"事故", "接触", "追突", "衝突事故", "故障車"
]),
("blind_spot", [
"死角", "見通しが悪い", "見えにくい", "陰", "遮られて", "遮蔽"
]),
("pedestrian_attention", [
"歩行者", "横断", "飛び出し", "自転車", "二輪"
]),
("intersection_complexity", [
"交差点", "合流", "分岐", "右左折", "信号"
])
]

出力ルール：
- 必ず次の2行だけ出力すること
- 1行目は「検出Event：...」
- 2行目は「要約：...」
- EVENT_RULES や説明文を繰り返してはいけない
- 要約は60文字以内
- 該当なしなら「検出Event：none」とする
- 箇条書きや * 記号を出力してはいけない

回答：
検出Event：
要約：`;
}

function getPromptRuntimeValues(){
  const mode = String(document.getElementById("canMode")?.value || "disabled").toLowerCase();

  let speedText = "-";
  let shiftText = "-";

  if(mode === "dummy"){
    const spd = document.getElementById("canDummyVehicleSpeed")?.value || "45";
    const shf = document.getElementById("canDummyShift")?.value || "D";
    speedText = `${spd} km/h`;
    shiftText = shf;
  }else{
    speedText = (document.getElementById("st_can_speed")?.textContent || "-").trim() || "-";
    shiftText = (document.getElementById("st_can_shift")?.textContent || "-").trim() || "-";
  }

  const yoloText = (document.getElementById("st_yolo_detect")?.textContent || "-").trim() || "-";
  return {speedText, shiftText, yoloText};
}

function applyVlmPromptTemplate(){
  const v = getPromptRuntimeValues();
  const el = document.getElementById("prompt");
  if(el){
    el.value = buildHighComplexPrompt(v.speedText, v.shiftText, v.yoloText);
  }
}

function updatePromptRuntimeValuesFromState(isRunning){
  if(!promptAutoEnabled()) return;
  if(!isRunning) return;
  applyVlmPromptTemplate();
}

function initCtrlTabs(){
  const btns = Array.from(document.querySelectorAll(".ctrl-tab-btn"));
  const panels = {
    output: document.getElementById("ctrl-panel-output"),
    can: document.getElementById("ctrl-panel-can"),
    yolo: document.getElementById("ctrl-panel-yolo"),
    vlm: document.getElementById("ctrl-panel-vlm"),
  };

  btns.forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const key = btn.dataset.ctrlTab;
      btns.forEach(b=>b.classList.remove("active"));
      Object.values(panels).forEach(p=>{ if(p) p.classList.remove("active"); });

      btn.classList.add("active");
      if(panels[key]) panels[key].classList.add("active");
    });
  });
}

function initMonitorTabs(){
  const btns = Array.from(document.querySelectorAll(".monitor-tab-btn"));
  const panels = {
    primary: document.getElementById("monitor-panel-primary"),
    secondary: document.getElementById("monitor-panel-secondary"),
    primary_input: document.getElementById("monitor-panel-primary_input"),
    secondary_input: document.getElementById("monitor-panel-secondary_input"),
    status: document.getElementById("monitor-panel-status"),
  };

  btns.forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const key = btn.dataset.monitorTab;
      btns.forEach(b=>b.classList.remove("active"));
      Object.values(panels).forEach(p=>{ if(p) p.classList.remove("active"); });

      btn.classList.add("active");
      if(panels[key]) panels[key].classList.add("active");

      try{ if(map) map.invalidateSize(); }catch(e){}
    });
  });
}

async function refreshAll(){
  const cfg = await api("/config");

  if(!dirty){
    document.getElementById("inputType").value = cfg.input.type ?? "video_file";
    document.getElementById("inputPath").value = cfg.input.path ?? "";
    document.getElementById("saveDir").value = cfg?.output?.save_dir ?? "/mnt/vlm_data/logs/events";

    document.getElementById("interval").value = cfg.pipeline.interval_sec ?? 2.0;
    document.getElementById("intervalVal").textContent = String(cfg.pipeline.interval_sec ?? 2.0);

    const ccfg = cfg?.can ?? {};
    const cdmy = ccfg?.dummy ?? {};
    document.getElementById("canMode").value = ccfg.mode ?? "disabled";
    document.getElementById("canDummyVehicleSpeed").value = String(cdmy.vehicle_speed ?? 42.5);
    document.getElementById("canDummyShift").value = String(cdmy.shift ?? "D");
    document.getElementById("canDummyAccelX").value = String(cdmy.accel_x ?? 0.12);
    document.getElementById("canDummyAccelY").value = String(cdmy.accel_y ?? -0.04);
    document.getElementById("canDummyAccelZ").value = String(cdmy.accel_z ?? 9.81);
    document.getElementById("canDummyPedalAccel").value = String(cdmy.pedal_accel ?? 18.0);
    document.getElementById("canDummyPedalBrake").value = String(cdmy.pedal_brake ?? 0.0);
    document.getElementById("canDummySteeringRate").value = String(cdmy.steering_rate ?? 6.5);

    if(!promptFocused && !promptDirty){
      document.getElementById("prompt").value = cfg.vlm.prompt ?? "";
    }

    const ve = (cfg?.vlm?.emit_interval_sec ?? cfg.pipeline.interval_sec ?? 2.0);
    document.getElementById("vlmInterval").value = ve;
    document.getElementById("vlmIntervalVal").textContent = String(ve);

    const vlmEnabled = String(cfg?.vlm?.engine ?? "stub").toLowerCase() !== "stub";
    setVlmBtn(vlmEnabled);

    yoloEnabled = Boolean(cfg?.yolo?.enabled ?? false);
    document.getElementById("yoloModel").value = cfg?.yolo?.model_name ?? "yolov8n.pt";
    document.getElementById("preset").value = "qwen25_7b_hf";
    document.getElementById("yoloConf").value = String(cfg?.yolo?.conf ?? 0.25);
    document.getElementById("yoloConfVal").textContent = String(cfg?.yolo?.conf ?? 0.25);
    document.getElementById("yoloPreviewHz").value = String(cfg?.yolo?.preview_hz ?? 3.0);
    document.getElementById("yoloPreviewHzVal").textContent = String(cfg?.yolo?.preview_hz ?? 3.0);

    if (!window.__evalUiInitialized) {
      document.getElementById("overlayEnabled").checked =
        Boolean(cfg?.evaluation?.overlay_enabled ?? true);
      document.getElementById("evalLogEnabled").checked =
        Boolean(cfg?.evaluation?.log_enabled ?? true);
      window.__evalUiInitialized = true;
    }
    setYoloBtn();

    const rcfg = cfg?.risk ?? {};
    document.getElementById("riskSceneWeight").value = String(rcfg.scene_complexity_weight ?? 0.35);
    document.getElementById("riskVruWeight").value = String(rcfg.vru_weight ?? 0.25);
    document.getElementById("riskBlindspotWeight").value = String(rcfg.blindspot_weight ?? 0.20);
    document.getElementById("riskSpeedMismatchWeight").value = String(rcfg.speed_mismatch_weight ?? 0.20);
    document.getElementById("riskMidThreshold").value = String(rcfg.mid_threshold ?? 35.00);
    document.getElementById("riskHighThreshold").value = String(rcfg.high_threshold ?? 55.00);

    speechEnabled = Boolean(cfg?.speech?.enabled ?? false);
    setSpeechBtn();
  }

  updateSeekEnabled();

  const sch = await api("/scheduler/status");
  document.getElementById("sch").textContent = sch.running ? "RUNNING" : "STOPPED";
  setVideoRunning(sch.running);

  // UI state (new)
  try{
    const st = await api("/ui/state");
    setStatusUI(st);
    updatePromptRuntimeValuesFromState(!!sch.running);
  }catch(e){
    document.getElementById("err").textContent = "ui/state error: " + String(e);
  }

  await refreshVideoStatus();
  try{ if(map) map.invalidateSize(); }catch(e){}
}

/* Events */
document.getElementById("btnSpeakTest").onclick = async ()=>{
  speechLastError = "test clicked";
  const el = document.getElementById("err");
  if(el) el.textContent = speechLastError;
  try{
    const r = await fetch("/speech/test", {method:"POST"});
    const j = await r.json();
    speechLastError = j.ok ? "server speech test requested" : ("server speech test error: " + String(j.error || "unknown"));
  }catch(e){
    speechLastError = "server speech test exception: " + String(e);
  }
  if(el) el.textContent = speechLastError;
};

document.getElementById("btnSpeech").onclick = async ()=>{
  if(!speechEnabled){ unlockSpeech(); }
  speechEnabled = !speechEnabled;
  setSpeechBtn();
  dirty=true;
  await applyConfig({speech_enabled: speechEnabled});
  dirty=false;
};

document.getElementById("btnYolo").onclick = async ()=>{
  yoloEnabled = !yoloEnabled;
  setYoloBtn();
  dirty=true;
  await applyConfig({yolo_enabled: yoloEnabled});
  dirty=false;
};

document.getElementById("btnVlm").onclick = async ()=>{
  const b = document.getElementById("btnVlm");
  const enabled = String(b?.dataset?.enabled ?? "1") === "1";

  dirty = true;
  if(enabled){
    await applyConfig({vlm_engine: "stub"});
    setVlmBtn(false);
  }else{
    const p = PRESET[document.getElementById("preset").value];
    await applyConfig({
      vlm_engine: p.vlm_engine,
      vlm_model_name: p.vlm_model_name
    });
    setVlmBtn(true);
  }
  dirty = false;
  await refreshAll();
};

document.getElementById("yoloConf").addEventListener("input", (e)=>{ dirty=true; document.getElementById("yoloConfVal").textContent = e.target.value; });
document.getElementById("yoloPreviewHz").addEventListener("input", (e)=>{ dirty=true; document.getElementById("yoloPreviewHzVal").textContent = e.target.value; });
document.getElementById("interval").addEventListener("input", (e)=>{ dirty=true; document.getElementById("intervalVal").textContent = e.target.value; });
document.getElementById("vlmInterval").addEventListener("input", (e)=>{ dirty=true; document.getElementById("vlmIntervalVal").textContent = e.target.value; });

document.getElementById("riskSceneWeight").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("riskVruWeight").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("riskBlindspotWeight").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("riskSpeedMismatchWeight").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("riskMidThreshold").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("riskHighThreshold").addEventListener("input", ()=>{ dirty=true; });

function clampRiskWeight(v){
  const n = Number(v);
  if(!isFinite(n)) return 0.00;
  return Math.max(0, Math.min(1, n));
}
function stepRiskWeight(id, delta){
  const el = document.getElementById(id);
  const cur = clampRiskWeight(el.value || 0);
  const next = Math.round((cur + delta) * 100) / 100;
  el.value = clampRiskWeight(next).toFixed(2);
  dirty = true;
}
document.getElementById("riskSceneWeightDec").onclick = ()=>stepRiskWeight("riskSceneWeight", -0.01);
document.getElementById("riskSceneWeightInc").onclick = ()=>stepRiskWeight("riskSceneWeight",  0.01);

document.getElementById("riskVruWeightDec").onclick = ()=>stepRiskWeight("riskVruWeight", -0.01);
document.getElementById("riskVruWeightInc").onclick = ()=>stepRiskWeight("riskVruWeight",  0.01);

document.getElementById("riskBlindspotWeightDec").onclick = ()=>stepRiskWeight("riskBlindspotWeight", -0.01);
document.getElementById("riskBlindspotWeightInc").onclick = ()=>stepRiskWeight("riskBlindspotWeight",  0.01);

document.getElementById("riskSpeedMismatchWeightDec").onclick = ()=>stepRiskWeight("riskSpeedMismatchWeight", -0.01);
document.getElementById("riskSpeedMismatchWeightInc").onclick = ()=>stepRiskWeight("riskSpeedMismatchWeight",  0.01);

function clampRiskThreshold(v){
  const n = Number(v);
  if(!isFinite(n)) return 0.00;
  return Math.max(0, Math.min(100, n));
}
function stepRiskThreshold(id, delta){
  const el = document.getElementById(id);
  const cur = clampRiskThreshold(el.value || 0);
  const next = Math.round((cur + delta) * 100) / 100;
  el.value = clampRiskThreshold(next).toFixed(2);
  dirty = true;
}
document.getElementById("riskMidThresholdDec").onclick = ()=>stepRiskThreshold("riskMidThreshold", -0.01);
document.getElementById("riskMidThresholdInc").onclick = ()=>stepRiskThreshold("riskMidThreshold",  0.01);

document.getElementById("riskHighThresholdDec").onclick = ()=>stepRiskThreshold("riskHighThreshold", -0.01);
document.getElementById("riskHighThresholdInc").onclick = ()=>stepRiskThreshold("riskHighThreshold",  0.01);

const seekEl = document.getElementById("seek");
function markSeeking(){
  seeking = true;
  seekDirty = true;
}
seekEl.addEventListener("pointerdown", markSeeking);
seekEl.addEventListener("mousedown", markSeeking);
seekEl.addEventListener("touchstart", markSeeking, {passive:true});
window.addEventListener("pointerup", ()=>{ seeking = false; });
window.addEventListener("mouseup",   ()=>{ seeking = false; });
window.addEventListener("touchend",  ()=>{ seeking = false; });
seekEl.addEventListener("input", ()=>{ markSeeking(); });

seekEl.addEventListener("change", async (e)=>{
  try{
    const typ = document.getElementById("inputType").value;
    if(typ === "camera"){ seekDirty=false; seeking=false; return; }
    const sec = Number(e.target.value || 0);
    await fetch("/video/seek?pos_sec=" + encodeURIComponent(sec), {method:"POST"});
  }catch(err){}
  setTimeout(()=>{ seekDirty = false; }, 800);
  setTimeout(()=>{ seeking = false; },  200);
});

document.getElementById("applyVlmPromptTemplateBtn").onclick = ()=>{
  applyVlmPromptTemplate();
  promptDirty = true;
  dirty = true;
};

document.getElementById("promptModeAuto").addEventListener("change", ()=>{
  if(document.getElementById("promptModeAuto").checked){
    applyVlmPromptTemplate();
  }
});
document.getElementById("promptModeManual").addEventListener("change", ()=>{});

document.getElementById("btnApplyPrompt").onclick = async ()=>{
  await applyConfig({prompt: document.getElementById("prompt").value});
  promptDirty = false;
  dirty=false; await refreshAll();
};
document.getElementById("prompt").addEventListener("keydown", async (e)=>{
  if(e.ctrlKey && e.key==="Enter"){ e.preventDefault(); await applyConfig({prompt: document.getElementById("prompt").value}); dirty=false; await refreshAll(); }
});
document.getElementById("prompt").addEventListener("input", ()=>{ promptDirty = true; dirty = true; });
document.getElementById("prompt").addEventListener("focus", ()=>{ promptFocused = true; });
document.getElementById("prompt").addEventListener("blur",  ()=>{ promptFocused = false; });

document.getElementById("btnApplyInput").onclick = async ()=>{
  const typ = document.getElementById("inputType").value;
  const path = document.getElementById("inputPath").value;
  await applyConfig({input_type: typ, input_path: path});
  try{ await api("/scheduler/stop", {method:"POST"}); }catch(e){}
  try{ await api("/scheduler/start", {method:"POST"}); }catch(e){}
  await waitSchedulerRunning(3000);
  dirty=false;
  await refreshAll();
};

document.getElementById("btnSave").onclick = async ()=>{
  const p = PRESET[document.getElementById("preset").value];
  const vlmEnabledNow = String(document.getElementById("btnVlm")?.dataset?.enabled ?? "1") === "1";
  const body = {
    input_type: document.getElementById("inputType").value,
    input_path: document.getElementById("inputPath").value,
    output_save_dir: document.getElementById("saveDir").value,

    pipeline_interval_sec: Number(document.getElementById("interval").value),
    vlm_emit_interval_sec: Number(document.getElementById("vlmInterval").value),
    prompt: document.getElementById("prompt").value,
    vlm_engine: vlmEnabledNow ? p.vlm_engine : "stub",
    vlm_model_name: p.vlm_model_name,
    yolo_enabled: yoloEnabled,
    yolo_model_name: document.getElementById("yoloModel").value,
    yolo_conf: Number(document.getElementById("yoloConf").value),
    yolo_preview_hz: Number(document.getElementById("yoloPreviewHz").value),
    evaluation_overlay_enabled: document.getElementById("overlayEnabled").checked,
    evaluation_log_enabled: document.getElementById("evalLogEnabled").checked,

    risk_scene_complexity_weight: Number(document.getElementById("riskSceneWeight").value),
    risk_vru_weight: Number(document.getElementById("riskVruWeight").value),
    risk_blindspot_weight: Number(document.getElementById("riskBlindspotWeight").value),
    risk_speed_mismatch_weight: Number(document.getElementById("riskSpeedMismatchWeight").value),
    risk_mid_threshold: Number(document.getElementById("riskMidThreshold").value),
    risk_high_threshold: Number(document.getElementById("riskHighThreshold").value),

    can_mode: document.getElementById("canMode").value,
    can_dummy_vehicle_speed: Number(document.getElementById("canDummyVehicleSpeed").value),
    can_dummy_shift: document.getElementById("canDummyShift").value,
    can_dummy_accel_x: Number(document.getElementById("canDummyAccelX").value),
    can_dummy_accel_y: Number(document.getElementById("canDummyAccelY").value),
    can_dummy_accel_z: Number(document.getElementById("canDummyAccelZ").value),
    can_dummy_pedal_accel: Number(document.getElementById("canDummyPedalAccel").value),
    can_dummy_pedal_brake: Number(document.getElementById("canDummyPedalBrake").value),
    can_dummy_steering_rate: Number(document.getElementById("canDummySteeringRate").value)
  };
  await applyConfig(body);
  dirty=false;
  document.getElementById("saveMsg").textContent = "保存しました";
  await refreshAll();
};

document.getElementById("btnStart").onclick = async ()=>{
  const p = PRESET[document.getElementById("preset").value];
  const vlmEnabledNow = String(document.getElementById("btnVlm")?.dataset?.enabled ?? "1") === "1";

  const body = {
    input_type: document.getElementById("inputType").value,
    input_path: document.getElementById("inputPath").value,
    output_save_dir: document.getElementById("saveDir").value,

    pipeline_interval_sec: Number(document.getElementById("interval").value),
    vlm_emit_interval_sec: Number(document.getElementById("vlmInterval").value),
    prompt: document.getElementById("prompt").value,
    vlm_engine: vlmEnabledNow ? p.vlm_engine : "stub",
    vlm_model_name: p.vlm_model_name,

    yolo_enabled: yoloEnabled,
    yolo_model_name: document.getElementById("yoloModel").value,
    yolo_conf: Number(document.getElementById("yoloConf").value),
    yolo_preview_hz: Number(document.getElementById("yoloPreviewHz").value),

    evaluation_overlay_enabled: document.getElementById("overlayEnabled").checked,
    evaluation_log_enabled: document.getElementById("evalLogEnabled").checked,

    risk_scene_complexity_weight: Number(document.getElementById("riskSceneWeight").value),
    risk_vru_weight: Number(document.getElementById("riskVruWeight").value),
    risk_blindspot_weight: Number(document.getElementById("riskBlindspotWeight").value),
    risk_speed_mismatch_weight: Number(document.getElementById("riskSpeedMismatchWeight").value),
    risk_mid_threshold: Number(document.getElementById("riskMidThreshold").value),
    risk_high_threshold: Number(document.getElementById("riskHighThreshold").value),

    can_mode: document.getElementById("canMode").value,
    can_dummy_vehicle_speed: Number(document.getElementById("canDummyVehicleSpeed").value),
    can_dummy_shift: document.getElementById("canDummyShift").value,
    can_dummy_accel_x: Number(document.getElementById("canDummyAccelX").value),
    can_dummy_accel_y: Number(document.getElementById("canDummyAccelY").value),
    can_dummy_accel_z: Number(document.getElementById("canDummyAccelZ").value),
    can_dummy_pedal_accel: Number(document.getElementById("canDummyPedalAccel").value),
    can_dummy_pedal_brake: Number(document.getElementById("canDummyPedalBrake").value),
    can_dummy_steering_rate: Number(document.getElementById("canDummySteeringRate").value)
  };

  await applyConfig(body);
  try{ await api("/scheduler/stop", {method:"POST"}); }catch(e){}
  try{ await api("/scheduler/start", {method:"POST"}); }catch(e){}
  await waitSchedulerRunning(3000);
  dirty = false;
  await refreshAll();
};
document.getElementById("btnStop").onclick  = async ()=>{ await api("/scheduler/stop",  {method:"POST"}); await refreshAll(); };

document.getElementById("inputType").addEventListener("change", ()=>{ dirty=true; updateSeekEnabled(); });
document.getElementById("inputPath").addEventListener("input",  ()=>{ dirty=true; });
document.getElementById("saveDir").addEventListener("input",   ()=>{ dirty=true; });
document.getElementById("yoloModel").addEventListener("change", ()=>{ dirty=true; });
document.getElementById("preset").addEventListener("change",    ()=>{ dirty=true; });

document.getElementById("canMode").addEventListener("change", ()=>{ dirty=true; updatePromptRuntimeValuesFromState(); });
document.getElementById("canDummyVehicleSpeed").addEventListener("input", ()=>{ dirty=true; updatePromptRuntimeValuesFromState(); });
document.getElementById("canDummyShift").addEventListener("change", ()=>{ dirty=true; updatePromptRuntimeValuesFromState(); });
document.getElementById("canDummyAccelX").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("canDummyAccelY").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("canDummyAccelZ").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("canDummyPedalAccel").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("canDummyPedalBrake").addEventListener("input", ()=>{ dirty=true; });
document.getElementById("canDummySteeringRate").addEventListener("input", ()=>{ dirty=true; });

/* Map init (placeholder) */
let map = null;
try{
  map = L.map('map', {zoomControl:true}).setView([35.681236, 139.767125], 14);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19}).addTo(map);

// --- GNSS track overlay (poll /gnss/latest) ---
let gnssPolyline = L.polyline([], { weight: 8 }).addTo(map);
let gnssLastTs = 0;

async function pollGnss() {
  try {
    const res = await fetch('/gnss/latest', { cache: 'no-store' });
    if (!res.ok) throw new Error('gnss http ' + res.status);
    const pt = await res.json();
    if (!pt || pt.lat == null || pt.lon == null) return;

    // 同じデータを何回も足さない（tsで判定）
    if (pt.ts && pt.ts <= gnssLastTs) return;
    if (pt.ts) gnssLastTs = pt.ts;

    const latlng = [pt.lat, pt.lon];
    gnssPolyline.addLatLng(latlng);

    // 重くならないように最大点数を制限（例: 3000点）
    const arr = gnssPolyline.getLatLngs();
    if (arr.length > 3000) {
      gnssPolyline.setLatLngs(arr.slice(arr.length - 3000));
    }

    // GPS Fix中だけ追従したいなら mode>=2 で
    // pt.mode: 0/1/2/3 (gpsdのmode)
    if ((pt.mode || 0) >= 2) {
      // map.panTo(latlng, { animate: false });  // 常に追従したい場合はコメント解除
    }
  } catch (e) {
    console.log('[gnss] poll error', e);
  }
}

// 5Hzくらい（200ms）で更新。重ければ 500ms に上げる
setInterval(pollGnss, 200);

  // ★これ重要：初期描画のサイズ確定
  setTimeout(()=>{ try{ map.invalidateSize(); }catch(e){} }, 50);

  // 画面リサイズでも追従
  window.addEventListener("resize", ()=>{ try{ map.invalidateSize(); }catch(e){} });
}catch(e){
  document.getElementById("mapHint").textContent = "Map init failed (offline?)";
}

/* Kick */
(async ()=>{
  initCtrlTabs();
  initMonitorTabs();
  await refreshAll();

  const btnUploadToggle = document.getElementById("btnUploadToggle");
  if(btnUploadToggle){
    btnUploadToggle.addEventListener("click", async () => {
      const st = await api("/ui/state");
      const current = !!st?.upload_enabled;
      await setUploadEnabled(!current);
    });
  }

  setInterval(refreshAll, 2000);
})(); // 1s更新
</script>
</body></html>"""

@router.get("/ui", response_class=HTMLResponse)
def ui():
  return HTML
