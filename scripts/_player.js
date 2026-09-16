//Player states.
const playerStateIdle = 0;
const playerStatePlaying = 1;
const playerStatePausing = 2;

/**
 * web player构造函数，外部传入画布, 播放url等
 *
 * @param {Object} canvas 画布对象.
 * @param {string} url 播放url
 * @param {Object} session 会话参数对象。 session.username, session.bussType
 */
function CanvasPlayer(canvas, url, session) {
    this.logger = null;
    try {
        this.logger = new Logger("player"); //在bing地图下会覆盖此Logger对象
    } catch (e) { }
    this.socketWorker = null;
    this.canvas = null;
    //this.devSession = dev;
    this.webglPlayer = null;
    this.url = url;
    this.canvas = canvas;
    this.playerState = playerStateIdle;
    this.pixFmt = 0;
    this.videoWidth = 0;
    this.videoHeight = 0;
    this.yLength = 0;
    this.uvLength = 0;
    this.isConnectServer = false;
    this.currentTime = 0;

    this.mBufferTimeMs = 0; //缓冲长度，单位毫秒，   0代表实时模 
    this.jsonRequest = null;
    this.sessionObj = { //播放session参数对象
        actionCode: 1, // 1-live; 2-replay; 3-fast replay; 4-listen
        speed: 1,
        deviceId: "",
        channel: 1,
        sessionId: "",
        st: "",
        et: "",
        streamSrc: "stream", //stream-实时媒体服务器 ；alarmserver-告警服务器；autoserver-下载服务器
        userName: "", //用户名
        funcCode: "" // 功能代号
    };


    if (typeof session !== "undefined") {
        this.sessionObj.userName = session.username;
        this.sessionObj.funcCode = session.bussType;
    }

    this.initSocketWorker();
    this.initCanvas();
}

CanvasPlayer.prototype.setBufferTimeMs = function (ms) {
    this.mBufferTimeMs = ms;
}

CanvasPlayer.prototype.initSocketWorker = function () {
    var self = this;
    //this.socketWorker = new Worker("/static/js/websocket.js");
    //this.url	= "http://47.115.83.226:33122/_bywasm_replay?1615255295834_999905_1_20210309095034_20210309095908";
    // 目前仅live和设备回放使用websocket
    if (this.logger) this.logger.log("http url:" + this.url);
    //this.url	= "https://172.16.50.210:9987/flvRouter.php?_bywasm_alarmreplay?1616461429850_800801_CH0_RDovc29mdHdhcmUvaHRkb2NzL3Zzc0ZpbGVzL2FsYXJtUmVjb3JkLzIwMjFfMDNfMjIvODAwODAxL2NoMDFfMjAyMTAzMjJfMDIxNTI5XzAyMTU1OV8wMzAubXA0";
    //this.url  =  http://172.16.50.219:33144/_bywasm_replay?1602640899149_888888_1_RTpcSG93ZW5cRG93bmxvYWRcMjAyMC0xMC0xM1w4ODg4ODhcY2gwMV8yMDIwMTAxM18wOTQ2MjZfMDk1OTI5XzAxLmFzZg==";
    var streamsrc = 1; //1-ajax, 2-ws
    var streamServerType = "stream"; // stream-实时媒体服务器 ；alarmserver-告警服务器；autoserver-下载服务器 
    if (this.url.indexOf("wasm_live?") != -1) //live
        streamsrc = 2; //	
    else if (this.url.indexOf("wasm_listen?") != -1) //监听
        streamsrc = 2;
    else if (this.url.indexOf("wasm_fastReplay?") != -1) //设备快进	
        streamsrc = 2; //
    else if (this.url.indexOf("wasm_alarmreplay?") != -1) //https://172.16.50.210:9987/flvRouter.php?_bywasm_alarmreplay?1616461429850_800801_CH0_RDovc29mdHdhcmUvaHRkb2NzL3Zzc0ZpbGVzL2hmdHAvODAwODAxL0FJLzIwMjEwMzIyLzE2MjcxOF83MC8wXzY0XzcwXzVfMTYxNjQzMDQzOC5tcDQ=
    {
        streamsrc = 2;
        streamServerType = "alarmserver";
    } else if (this.url.indexOf("wasm_slicereplay?") != -1 || this.url.indexOf("sliceflvRouter") != -1) //https://172.16.50.210:9987/flvRouter.php?_bywasm_alarmreplay?1616461429850_800801_CH0_RDovc29mdHdhcmUvaHRkb2NzL3Zzc0ZpbGVzL2hmdHAvODAwODAxL0FJLzIwMjEwMzIyLzE2MjcxOF83MC8wXzY0XzcwXzVfMTYxNjQzMDQzOC5tcDQ=
    {
        streamsrc = 2;
        streamServerType = "alarmserver";
    } else if (this.url.indexOf("wasm_replay?") != -1) // device replay or autodown server replay
    {
        streamsrc = 2;
        if (this.url.match(/\d{14}_\d{14}/g) == null) //自动下载
            streamServerType = "autoserver";
    }
    //streamsrc	= 1;
    if (streamsrc == 2) {
        this.jsonRequest = this.httpUrl2JsonRequest(this.url); //输入http url
        if (this.jsonRequest == null) {
            this.logger.logError("Invalid request http url: " + this.url);
            return;
        }

        let _wsurl = "";
        let _proc = this.url.substring(0, this.url.indexOf("//"));
        let _procAft = this.url.substring(this.url.indexOf("//") + 2);
        let _ipPort = _procAft.substring(0, _procAft.indexOf("/"));
        let _serverIp = _ipPort.substring(0, _ipPort.indexOf(":"));
        let _serverPort = _ipPort.substring(_ipPort.indexOf(":") + 1);

        if (_proc == "http:" || _proc == "HTTP:")
            _wsurl = "ws://" + _serverIp + ":" + _serverPort + "/" + streamServerType;
        else {	// nginx forward
            //_wsurl = "wss://" + _serverIp + ":" + g_cnfServerSSLPort + "/" + streamServerType;	// 直接指向节点的nginx方案
            _wsurl = "wss://" + _serverIp + ":" + g_cnfServerSSLPort + "/" + streamServerType + "?ipaddr=127.0.0.1";
            if (_serverIp != window.location.hostname)	// 针对子节点
                _wsurl = "wss://" + window.location.hostname + ":" + g_cnfServerSSLPort + "/" + streamServerType + "?ipaddr=" + _serverIp;
        }

        this.url = _wsurl;
    }

    //streamsrc	= "dist/player/ajaxstream.js";
    if (streamsrc == 1)
        this.socketWorker = new Worker("/vss/dist/player/ajaxstream.js?v=1.8.6");
    else
        this.socketWorker = new Worker("/vss/dist/player/hwwebsocket.js?v=1.8.6");
    this.streamsrc = streamsrc;

    this.socketWorker.onmessage = function (evt) {
        var objData = evt.data;
        switch (objData.t) {
            case kInitDecoderRsp:
                self.onStreamStart(objData);
                break;
            case KWebSocket_Close:
                self.onStreamStop();
                break;
            case KWebSocket_Message:
                self.onStream(objData.d);
                break;
            case KWebSocket_Open:
                break;
            case kVideoFrame:
                self.onVideoFrame(objData);
                break;
            case kAudioFrame:
                self.onAudioFrame(objData);
                break;
        }
    };

    this.initUrlConnect();
};

CanvasPlayer.prototype.initUrlConnect = function () {
    var objData = {
        t: KWebSocket_ConnectReq,
        u: this.url,
        s: this.jsonRequest,
        ob: this.sessionObj
    };
    this.socketWorker.postMessage(objData);
};

CanvasPlayer.prototype.initCanvas = function () {
    if (!this.canvas) {
        ret = {
            e: -2,
            m: "Canvas not set",
        };
        success = false;
        this.logger.logError("[ER] playVideo error, canvas empty.");
        return;
    }
    this.webglPlayer = new WebGLPlayer(this.canvas, {
        preserveDrawingBuffer: false,
    });
};

CanvasPlayer.prototype.play = function (url) {

    if (url) {
        this.url = url;
        //    if( this.socketWorker==null ) 
        //    	this.initSocketWorker();
        this.initUrlConnect();
    }

    var success = false;
    do {
        if (this.playerState == playerStatePausing) {
            this.resumePlaying();
            break;
        }
        if (this.playerState == playerStatePlaying) {
            break;
        }
        if (!this.socketWorker) {
            ret = {
                e: -3,
                m: "Downloader not initialized",
            };
            this.logger.logError("[ER] Downloader not initialized.");
            break;
        }

        if (!this.webglPlayer) {
            ret = {
                e: -3,
                m: "WebglPlayer not initialized",
            };
            this.logger.logError("[ER] WebglPlayer not initialized.");
            break;
        }
        //this.logger.log(this.websocketurl);
        this.initDecoder();
        this.playerState = playerStatePlaying;
        success = true;
    } while (false);
};

CanvasPlayer.prototype.resumePlaying = function () {
    this.playerState = playerStatePlaying;

    if (this.streamsrc == 2)
        return this.playControl(2, 0);

    var objData = {
        t: KWebSocket_StreamStart,
    };
    this.socketWorker.postMessage(objData);
};

CanvasPlayer.prototype.playControl = function (action, offset) {
    this.playerState = playerStatePlaying;
    var objData = {
        t: KWebSocket_playControl,
        d: action,
        o: offset
    };
    this.socketWorker.postMessage(objData);
};

CanvasPlayer.prototype.pause = function () {
    this.playerState = playerStatePausing;

    if (this.streamsrc == 2)
        return this.playControl(1, 0);

    var objData = {
        t: KWebSocket_StreamStop,
    };
    this.socketWorker.postMessage(objData);
};

CanvasPlayer.prototype.fullscreen = function () {
    if (this.webglPlayer) {
        this.webglPlayer.fullscreen();
    }
};

CanvasPlayer.prototype.openAudio = function (isAudio) {
    if (isAudio == true) {
        this.pcmPlayer = new PCMPlayer({
            encoding: "16bitInt",
            channels: 1,
            sampleRate: 8000,
            flushingTime: 200,
        });
    } else {
        this.pcmPlayer = null;
    }
};

CanvasPlayer.prototype.openAudio24k = function (isAudio) {
    if (isAudio == true) {
        this.pcmPlayer = new PCMPlayer({
            encoding: "16bitInt",
            channels: 1,
            sampleRate: 24000,
            flushingTime: 200,
        });
        this.pcmSampleRate = 24000;
    } else {
        this.pcmPlayer = null;
    }
};


CanvasPlayer.prototype.onStream = function (data) {
    var objData = {
        t: kFeedDataReq,
        d: data,
    };
    this.decodeWorker.postMessage(objData);
};

CanvasPlayer.prototype.onStreamStart = function (evt) {
    if (evt.d > 0) {
        return;
    }
    var objData = {
        t: KWebSocket_StreamStart,
    };
    this.socketWorker.postMessage(objData);
};

CanvasPlayer.prototype.onStreamStop = function (evt) {
    this.socketWorker.terminate();
    return;
};

CanvasPlayer.prototype.unload = function () {
    this.playerState = playerStatePausing;
    var objData = {
        t: KWebSocket_StreamStop,
    };
    this.socketWorker.postMessage(objData);

    // release
    //this.socketWorker	= null;
    this.webglPlayer.gl = null;
    this.webglPlayer = null;

    //this.logger.log("----send stop commond");
};

CanvasPlayer.prototype.onVideoFrame = function (frame) {
    if (this.videoWidth == 0) {
        this.videoWidth = frame.w;
        this.videoHeight = frame.h;
        this.yLength = this.videoWidth * this.videoHeight;
        this.uvLength = (this.videoWidth / 2) * (this.videoHeight / 2);
    }
    this.displayVideoFrame(frame);
    // this.logger.log("frame time offset(s)="+frame.ts);
};

CanvasPlayer.prototype.displayVideoFrame = function (frame) {
    var data = new Uint8Array(frame.d);
    this.renderVideoFrame(data);
    this.currentTime = frame.ts;
};

CanvasPlayer.prototype.displayNextVideoFrame = function () { };

CanvasPlayer.prototype.renderVideoFrame = function (data) {
    if (this.webglPlayer)
        this.webglPlayer.renderFrame(
            data,
            this.videoWidth,
            this.videoHeight,
            this.yLength,
            this.uvLength
        );
};

CanvasPlayer.prototype.onAudioFrame = function (frame) {


    this.displayAudioFrame(frame);
};

CanvasPlayer.prototype.displayAudioFrame = function (frame) {
    if (this.pcmPlayer) {
        if (this.pcmSampleRate == 24000) {
            this.pcmPlayer.feed(this.Pcm8t24(frame.d));
            return true;
        }
        this.pcmPlayer.feed(frame.d);
    }
    return true;
};

CanvasPlayer.prototype.initDecoder = function (evt) {

    if (this.sessionObj.streamSrc == "alarmserver" || this.sessionObj.streamSrc == "autoserver") // server media
        this.mBufferTimeMs = 0;

    var objData = {
        t: kInitDecoderReq,
        buff: this.mBufferTimeMs,
    };
    this.socketWorker.postMessage(objData);
};



CanvasPlayer.prototype.Pcm8t24 = function (pcmUint8Arr) {

    var outArr = new Uint8Array(pcmUint8Arr.byteLength * 3);

    for (var i = 0; i < pcmUint8Arr.byteLength; i += 2) {
        // ui8a[i] = textBuffer.charCodeAt(j) & 0xff;
        let outIndex = i * 3;
        outArr[outIndex] = pcmUint8Arr[i];
        outArr[outIndex + 1] = pcmUint8Arr[i + 1];
        outArr[outIndex + 2] = pcmUint8Arr[i];
        outArr[outIndex + 3] = pcmUint8Arr[i + 1];
        outArr[outIndex + 4] = pcmUint8Arr[i];
        outArr[outIndex + 5] = pcmUint8Arr[i + 1];
    }
    return outArr;
}

CanvasPlayer.prototype.httpUrl2JsonRequest = function (httpUrl) {

    //"{\"action\":\"3001\",\"payload\":{\"sessionID\":\"11\",\"deviceID\":\"20198002\",\"channel\":\"1\",\"workMode\":\"1\"}}";	
    //live:{"action":"3000","payload":{"sessionID":"1","deviceID":"20200148","stream":"0","channel":"1","bufferTimeMs":"3000"}}
    let _urlPara = httpUrl.substring(httpUrl.lastIndexOf("?") + 1);


    if (httpUrl.indexOf("wasm_live?") != -1) // live
    {
        this.sessionObj.actionCode = 1;
        //1591212324_99990001_1_0   分别是sessionid, deviceID, chnum, mainstream(0/1)
        // let _rex = /(\w+)_([\w\-]+)_(\d+)_(\d+)/g;
        // let _paraArr = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];

        let _paraArr = [
            [0, ..._urlPara.split('_')]
        ]

        this.sessionObj.deviceId = _paraArr[0][2];
        this.sessionObj.sessionId = new Date().getTime();
        this.sessionObj.channel = _paraArr[0][3];
        return "{\"action\":\"3000\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"stream\":\"" + _paraArr[0][4] + "\",\"bufferTimeMs\":\"2000\",\"username\":\"" + this.sessionObj.userName + "\",\"bussType\":\"" + this.sessionObj.funcCode + "\"}}";
    } else if (httpUrl.indexOf("wasm_listen?") != -1) // listen
    {
        this.sessionObj.actionCode = 4;
        //1591212324_99990001_1_0   分别是sessionid, deviceID, chnum, mainstream(0/1)
        // let _rex = /(\w+)_([\w\-]+)_(\d+)_(\d+)/g;
        // let _paraArr = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];


        let _paraArr = [
            [0, ..._urlPara.split('_')]
        ]





        this.sessionObj.deviceId = _paraArr[0][2];
        this.sessionObj.sessionId = new Date().getTime();
        this.sessionObj.channel = _paraArr[0][3];
        return "{\"action\":\"3001\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"workMode\":\"0\",\"username\":\"" + this.sessionObj.userName + "\",\"bussType\":\"" + this.sessionObj.funcCode + "\"}}";
    } else if (this.url.indexOf("wasm_alarmreplay?") != -1) {
        //?_bywasm_alarmreplay?1616461429850_800801_CH0_RDovc29mdHdhcmUvaHRkb2NzL3Zzc0ZpbGVzL2hmdHAvODAwODAxL0FJLzIwMjEwMzIyLzE2MjcxOF83MC8wXzY0XzcwXzVfMTYxNjQzMDQzOC5tcDQ=
        // let _rex = /(\w+)_([\w\-]+)_(\w+)_(.+)/g;
        // let _paraArr = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];



        let _paraArr = [
            [0, ..._urlPara.split('_')]
        ]



        this.sessionObj.deviceId = _paraArr[0][2];
        this.sessionObj.sessionId = new Date().getTime();
        this.sessionObj.channel = parseInt(_paraArr[0][3]);
        this.sessionObj.streamSrc = "alarmserver";
        let _filename = window.atob(_paraArr[0][4]);
        _filename = _filename.replace(/\\/g, "\\\\");
        //return "{\"action\":\"3003\",\"payload\":{\"sessionID\":\""+this.sessionObj.sessionId+"\",\"deviceID\":\""+ _paraArr[0][2] +"\",\"channel\":\""+ _paraArr[0][3] +"\",\"workMode\":\"0\"}}";
        return " {\"action\":\"3003\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"startTime\":\"" + "" + "\",\"stopTime\":\"" + "" + "\",\"offset\":\"0\",\"fileName\":\"" + _filename + "\",\"bufferTimeMs\":\"2500\",\"actionType\":\"1\"}}";

    } else if (this.url.indexOf("wasm_slicereplay?") != -1 || this.url.indexOf("sliceflvRouter") != -1) { //中心录像片段回放
        //?_bywasm_slicereplay?1616461429850_800801_1_180_RDovc29mdHdhcmUvaHRkb2NzL3Zzc0ZpbGVzL2hmdHAvODAwODAxL0FJLzIwMjEwMzIyLzE2MjcxOF83MC8wXzY0XzcwXzVfMTYxNjQzMDQzOC5tcDQ=
        // token_deviceId_channle_offset_filePath
        // let _rex = /(\w+)_([\w\-]+)_(\w+)_(.+)/g;
        // let _paraArr = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];

        let _paraArr = [
            [0, ..._urlPara.split('_')]
        ]

        this.sessionObj.deviceId = _paraArr[0][2];
        this.sessionObj.sessionId = new Date().getTime();
        this.sessionObj.channel = parseInt(_paraArr[0][3]);
        this.sessionObj.offset = parseInt(_paraArr[0][4]);
        this.sessionObj.streamSrc = "alarmserver";

        let _filename = window.atob(_paraArr[0][5]);
        _filename = _filename.replace(/\\/g, "\\\\");
        this.sessionObj.fileName = _filename;
        //return "{\"action\":\"3003\",\"payload\":{\"sessionID\":\""+this.sessionObj.sessionId+"\",\"deviceID\":\""+ _paraArr[0][2] +"\",\"channel\":\""+ _paraArr[0][3] +"\",\"workMode\":\"0\"}}";
        return " {\"action\":\"3003\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"startTime\":\"" + "" + "\",\"stopTime\":\"" + "" + "\",\"offset\":\"" + parseInt(_paraArr[0][4]) + "\",\"fileName\":\"" + _filename + "\",\"bufferTimeMs\":\"2500\",\"actionType\":\"1\"}}";

    } else if (httpUrl.indexOf("wasm_replay?") != -1 || httpUrl.indexOf("wasm_fastReplay?") != -1) // device replay 
    {
        if (this.url.match(/\d{14}_\d{14}/g) == null) //自动下载无开始时间和结束时间
        {
            //?1602640899149_888888_1_RTpcSG93ZW5cRG93bmxvYWRcMjAyMC0xMC0xM1w4ODg4ODhcY2gwMV8yMDIwMTAxM18wOTQ2MjZfMDk1OTI5XzAxLmFzZg==";
            // let _rex = /(\w+)_([\w\-]+)_(\w+)_(.+)/g;
            // let _paraArr2 = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];



            let _paraArr = [
                [0, ..._urlPara.split('_')]
            ]


            this.sessionObj.deviceId = _paraArr[0][2];
            this.sessionObj.sessionId = new Date().getTime();
            this.sessionObj.channel = parseInt(_paraArr[0][3]);
            this.sessionObj.streamSrc = "autoserver";
            let _filename = window.atob(_paraArr[0][5]);
            _filename = _filename.replace(/\\/g, "\\\\");
            return " {\"action\":\"3003\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"startTime\":\"" + "" + "\",\"stopTime\":\"" + "" + "\",\"offset\":\"" + _paraArr[0][4] + "\",\"fileName\":\"" + _filename + "\",\"bufferTimeMs\":\"2500\",\"actionType\":\"1\",\"username\":\"" + this.sessionObj.userName + "\",\"bussType\":\"" + this.sessionObj.funcCode + "\"}}";
        }

        //replay?2591212324_20191122_1_20200810110900_20200810112800
        // let _rex = /(\w+)_([\w\-]+)_(\d+)_(\d{14})_(\d{14})/g;
        // if (httpUrl.indexOf("wasm_fastReplay?") != -1)
        //     _rex = /(\w+)_([\w\-]+)_(\d+)_(\d{14})_(\d{14})_(\d{1})/g;

        // let _paraArr = [..._urlPara.matchAll(_rex)]; //[...content.matchAll(reg)];

        let _paraArr = [
            [0, ..._urlPara.split('_')]
        ]






        let _startTime = _paraArr[0][5];
        let _st = _startTime.substring(0, 4) + "-";
        _st += _startTime.substring(4, 6) + "-";
        _st += _startTime.substring(6, 8) + " ";
        _st += _startTime.substring(8, 10) + ":";
        _st += _startTime.substring(10, 12) + ":";
        _st += _startTime.substring(12);
        let _endTime = _paraArr[0][6];
        let _et = _endTime.substring(0, 4) + "-";
        _et += _endTime.substring(4, 6) + "-";
        _et += _endTime.substring(6, 8) + " ";
        _et += _endTime.substring(8, 10) + ":";
        _et += _endTime.substring(10, 12) + ":";
        _et += _endTime.substring(12);

        this.sessionObj.st = _st;
        this.sessionObj.et = _et;
        if (httpUrl.indexOf("wasm_replay?") != -1)
            this.sessionObj.actionCode = 2;
        else {
            this.sessionObj.actionCode = 3;
            this.sessionObj.speed = parseInt(_paraArr[0][7]);
        }

        this.sessionObj.deviceId = _paraArr[0][2];
        this.sessionObj.sessionId = new Date().getTime();
        this.sessionObj.channel = _paraArr[0][3];
        return " {\"action\":\"3003\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + _paraArr[0][2] + "\",\"stream\":\"" + _paraArr[0][4] + "\",\"channel\":\"" + _paraArr[0][3] + "\",\"startTime\":\"" + _st + "\",\"stopTime\":\"" + _et + "\",\"offset\":\"0\",\"fileName\":\"\",\"bufferTimeMs\":\"2500\",\"actionType\":\"1\",\"username\":\"" + this.sessionObj.userName + "\",\"bussType\":\"" + this.sessionObj.funcCode + "\"}}";
    }

};