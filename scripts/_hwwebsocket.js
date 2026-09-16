importScripts("./common.js?v=1.6.0");
importScripts("./decoder.js?v=1.6.0");
var _lastIndex2 = 0;


function textToArrayBuffer(textBuffer, startOffset, endOffset) {

    var len = textBuffer.length - startOffset;

    if (endOffset > startOffset && (endOffset - startOffset) < len)
        len = endOffset - startOffset;


    //var arrayBuffer = new ArrayBuffer(len);
    //var ui8a = new Uint8Array(arrayBuffer, 0);
    var ui8a = new Uint8Array(len);

    let _start = Date.now();
    var i = 0;
    for (i = 0, j = startOffset; i < len; i++, j++) {
        ui8a[i] = textBuffer.charCodeAt(j) & 0xff;
    }
    // console.log("spend ms="+(Date.now()-_start  )+"; loopCounter="+i);	// 这里需要优化，时间长了会运行越来越慢，尤其对高清
    return ui8a;
}

function WSSource() {
    this.logger = new Logger("websocket");
    this.devSession = null;

    this.jsonRequest = null;
    this.channel = 1;
    this.socket = null;
    this.url = null;
    this.decoder = new WebDecoder();

    this.isActive = false;
    this.souceIndex = parseInt(Math.random() * 100 + 1);
    this._xhr = null;
    this.mPlaymode = 1; // 播放模式，0-实时，1-cache  . 如果浏览器不支持定时器，则自动切换到实时模式
    this.interval = null;

    // config
    this.mCnfVideoBufferTime = 1000; // ms
    this.mCnfVideoBufferTimeMin = 200; // ms,小于此缓冲，就重新暂停等待缓冲满。

    /*
     *  {	//播放session参数对象: sessionObj
			actionCode: 1,		// 1-live; 2-replay; 3-fast replay; 4-listen
			speed: 1,
			deviceId: "",
			channel: 1,
			sessionId: "",
			st:"",
			et:"",
			streamSrc:""  //stream-实时媒体服务器 ；alarmserver-告警服务器；autoserver-下载服务器
		};
     * */
    this.sessionObj = null; //封装了请求类型

    this.speedContorlSend = false; //是否已发control command
    // all buffer
    this._recvBuffer = null;
    this._mAudioBufferArray = new Array(); //音频帧数组
    this._mVideoBufferArray = new Array(); //视频帧数组

    // 状态变量
    this.streamOffset = 0; //当前播放视频指针偏移量
    this.mCalStreamOffset = 0; //当前获取最大时间戳的流偏移量
    this.mVideoReferLocalTime = -1; // 本地视频参考时钟，ms。 默认值-1 
    this.mVideoReferHProcTime = 0 // 传输参考时钟, ms。
    this.mVideoCurrentFrame = null;


    this.mVideoPlayTimeMs = 0; //最后播放时刻
    this.mVideoBufferMaxtimetamp = 0; //缓存中最大时间戳
    this.mPlayState = 0; //播放状态，0-buffering,1-normal play,
    this.mPlayConrolState = 2; //当前播放控制指令。0-seek 1-暂停，2-恢复正常播放，3-播放关键帧

    this.mBufferParseing = 0;
    this.mFastPlaying = false; //快速播放状态，为了追赶延时

}

// 解码线程
WSSource.prototype.decodeLoop = function() {

    if (this.isActive) {
        try {
            requestAnimationFrame(this.decodeLoop.bind(this));
        } catch (e) {
            //this.mPlaymode	= 0;
            this.loopDoPlay = this.loopDoPlay.bind(this);
            this.interval = setInterval(this.loopDoPlay, 10);
            return false;
        }
        //mozRequestAnimationFrame(this.decodeLoop.bind(this));
        // return true;
    }

    this.loopDoPlay();
}
WSSource.prototype.loopDoPlay = function() {

        //获取缓冲时间长度
        let _start1 = Date.now();

        let _bufferDurationMs = 0; //缓纯中时间长度

        if (this.mPlayConrolState == 1) //暂停
            return;

        //if( this.mPlayState	== 0 ) 
        { //缓冲模式下才计算缓冲大小，因为比较耗时
            //this.calBufferDuration();	//ws方案不需要计算
            _bufferDurationMs = this.mVideoBufferMaxtimetamp - this.mVideoPlayTimeMs;
            //if( _bufferDurationMs>this.mCnfVideoBufferTime+500 )
            //if( _bufferDurationMs>this.mCnfVideoBufferTime+500 )
            //	this.logger.log( "video buffer ms=" + _bufferDurationMs + "("+ this.mVideoBufferMaxtimetamp +"-"+this.mVideoPlayTimeMs+")");
        }


        if (_bufferDurationMs <= this.mCnfVideoBufferTime && this.mPlayState == 0 //缓冲中
            &&
            this.mVideoReferLocalTime != -1 //本次会话第一帧立刻播放，跳过缓冲	
        ) //缓冲中
        {
            return;
        }

        // 解码播放	
        let _start = Date.now();
        if (this.mVideoCurrentFrame == null) {
            this.mVideoCurrentFrame = this.getNextFrameFromBuffer();
        }
        if (this.mVideoCurrentFrame == null) { //获取失败，则重新进入缓冲模式	
            this.mPlayState = 0;
            if (this.mVideoReferLocalTime != -1)
                this.mVideoReferLocalTime = 0;
            this.mVideoReferHProcTime = 0;
            return;
        }

        let _currentFrameTime = this.getPackageTimestamp(this.mVideoCurrentFrame);
        //this.logger.log("===========between interval="+ (_currentFrameTime-this.mVideoPlayTimeMs));

        if (_bufferDurationMs > (this.mCnfVideoBufferTime + 5000)) //延时太大，就进入快速播放状态
            this.mFastPlaying = true;

        if (this.mFastPlaying && _bufferDurationMs < this.mCnfVideoBufferTime) { //退出快速播放，重新进入缓冲区刚满的状态
            this.mFastPlaying = false;
            this.mPlayState = 0;
            this.mVideoReferLocalTime = 0;
        }

        // 判断是否到达播放时间
        if (0 ||
            (Date.now() - this.mVideoReferLocalTime >= (_currentFrameTime - this.mVideoReferHProcTime))
            //	|| ( Date.now()-this.lastDecodeTimeMs >= (_currentFrameTime-this.mVideoPlayTimeMs) )			
            ||
            this.mVideoReferLocalTime == -1 //还未开始
            ||
            this.mPlayState == 0 //缓冲区填满后立即播放
            ||
            this.mFastPlaying //缓存太大，立即播放
        ) //开始播放
        {
            if (this.mVideoReferLocalTime == -1) { //播放第一帧后进入缓冲模式
                this.mVideoReferLocalTime = 0;
                this.mVideoReferHProcTime = 0;
                this.mPlayState = 0; //为进入缓冲模式
            } else {
                this.mPlayState = 1; //切到正常播放状态
                if (this.mVideoReferLocalTime == 0) {
                    this.mVideoReferLocalTime = Date.now(); //播放第一帧时间时，设定参考时间
                    this.mVideoReferHProcTime = _currentFrameTime;
                }
            }


            //this.logger.log( "getframe spend tms[" + this.souceIndex + "]=" + (Date.now()-_start) + ";ret="+ 1 +";fType="+this.getFrameType(this.mVideoCurrentFrame) );
            //this.logger.log("===========decode interval="+ (Date.now()-this.lastDecodeTimeMs));
            this.lastDecodeTimeMs = Date.now();
            let _rr = this.decoder.decodeOnepacket(this.mVideoCurrentFrame);
            this.mVideoPlayTimeMs = _currentFrameTime;
            this.mVideoCurrentFrame = null; //播放完后就清理掉

            // play audio
            while (true) {
                let _audioBuff = this._mAudioBufferArray.shift();
                if (_audioBuff == undefined || _audioBuff == null) break;
                this.decoder.decodeOnepacket(_audioBuff);

                if (this.getPackageTimestamp(_audioBuff) > _currentFrameTime) {
                    break;
                }
            }
        }

    }
    //从buffer中获取下一帧数据
WSSource.prototype.getNextFrameFromBuffer = function() {

    // 0-无效，1-i frame,2-p frame,3-audio frame
    //this.logger.log( "frame length[" + this.souceIndex + "]=" + (Date.now()-_start) + "; bufferlen=" + packLen );
    if (this._mVideoBufferArraylength < 1) return;
    return this._mVideoBufferArray.shift();
}

WSSource.prototype.getPackageTimestamp = function(frameBufferArray) {
    let _timeMs = 0,
        _timeMs2 = 0;

    //http wasm frame Header： frame-2Bytes, time offset-2Bytes,  frame data len-4Bytes, timestamp ms-4Bytes
    _timeMs += frameBufferArray[8];
    _timeMs += frameBufferArray[9] << 8;
    _timeMs += frameBufferArray[10] << 16;
    _timeMs += frameBufferArray[11] << 24;
    return _timeMs;

    // //websocket wasm frame Header： frame-2Bytes, time offset-2Bytes, timestamp us-8Bytes
    // let byteDataView = new DataView(frameBufferArray.buffer, 8); //飘过前面8个字节的消息头
    // let _bigIntTimeUs = byteDataView.getBigUint64(4, true); //
    // _timeMs2 = parseInt(BigInt(_bigIntTimeUs / 1000 n).toString());
    // return _timeMs2;

}
WSSource.prototype.getFrameType = function(frameBufferArray) {
    let packType = 0; // 0-invalid,  1-i video, 2-p video, 3-audio frame
    packType += frameBufferArray[0];
    packType += frameBufferArray[1] << 8;
    return packType;
}

WSSource.prototype.init = function() {
    this.decoder.init();
    // var ret = this.decoder.openDecoder();
    var objData = {
        t: kInitDecoderRsp,
        d: 0
    };
    self.postMessage(objData);
};

WSSource.prototype.connectServer = function(evt) {

    console.log('--------connectServer');

    this.jsonRequest = evt.s;
    this.url = evt.u;
    this.sessionObj = evt.ob;

    this.sessionState = 0;
    this.logger.log("init websocket " + this.url + "; request " + this.jsonRequest);
    console.log(this.url)
    this.socket = new WebSocket(this.url);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onmessage = this.onMessage.bind(this);
    this.socket.onopen = this.onOpen.bind(this);
    this.socket.onerror = this.onClose.bind(this);
    this.socket.onclose = this.onClose.bind(this);
};

WSSource.prototype.onMessage = function(evt) {

    //var _u8Buffer	= new Uint8Array(evt.data);
    var _resDataView = new DataView(evt.data);

    //var aaa = _resDataView.getUint8(0);
    if (_resDataView.getUint8(0) != 0x48) {
        this.logger.log("Recv error data, byte0=" + _resDataView.getUint8(0));
        return;
    }
    var _actionCode = _resDataView.getUint16(2, true);
    //this.logger.log("Recv response. code="+ _actionCode +"; len="+_resDataView.byteLength);
    if (_actionCode == 2) // jason
    {
        var dataString = "";
        for (var i = 8; i < _resDataView.byteLength; i++) {
            if (_resDataView.getUint8(i) == 0) break; // \0
            dataString += String.fromCharCode(_resDataView.getUint8(i));
        }
        //dataString +=  String.fromCharCode(0);	//²»ÄÜÓÐ\0
        this.logger.log("Recv json response=" + dataString);
        var _jsonObj = JSON.parse(dataString);
        if (parseInt(_jsonObj.error) != 0) {
            this.logger.log("request faild! errorcode=" + _jsonObj.error);
            return;
        }
        this.sessionState = 1; //ÇëÇó³É¹¦
    } else if (_actionCode == 1000) // media data
    {
        var _arrayBuffer = new Uint8Array(_resDataView.buffer, 8);


        //let _bigIntTimeUs	= _resDataView.getBigUint64(12, true);	

        if (this.sessionObj.actionCode == 3)
            this.sendFastRequest();
        if (this.mCnfVideoBufferTime > 100 && this.sessionObj.actionCode != 4 && this.sessionObj.actionCode != 3) {
            if (_arrayBuffer[0] == 3) { //audio
                this._mAudioBufferArray.push(_arrayBuffer);
                // this.logger.log("Recv response. code="+ _actionCode +"; len="+_resDataView.byteLength);
            } else if (_arrayBuffer[0] == 1 || _arrayBuffer[0] == 2) // video
            {
                this._mVideoBufferArray.push(_arrayBuffer);
                this.mVideoBufferMaxtimetamp = this.getPackageTimestamp(_arrayBuffer);
                // this.logger.log("packt tm="+this.mVideoBufferMaxtimetamp);
            }

        } else
            this.decoder.decodeOnepacket(_arrayBuffer);

    }


    //	this.logger.log("Recv stream frame, len="+ evt.data);
    if (this.isActive) {
        //this.decoder.decodeOnepacket(evt.data);
    }
};

WSSource.prototype.onOpen = function() {
    this.logger.log("connected!");

    // Send howen json request
    var hwHeaderLen = 8;
    var jsonRequest = this.jsonRequest; //"{\"action\":\"3001\",\"payload\":{\"sessionID\":\"11\",\"deviceID\":\"20198002\",\"channel\":\"1\",\"workMode\":\"1\"}}";	//¶Ô½²
    var buffer = new ArrayBuffer(jsonRequest.length + hwHeaderLen);
    var sendView = new DataView(buffer);
    console.log(jsonRequest)
    // add message header
    var i = 0;
    sendView.setInt8(i++, 0x48); //'H'
    sendView.setInt8(i++, 1); // version:1
    sendView.setInt16(i, 2, true); // action code: 2£¬little endian.  2-json request, 5-media data
    i += 2;
    sendView.setInt32(i, jsonRequest.length, true); // request json length£¬little endian
    i += 4;
    for (var j = 0; j < jsonRequest.length; j++) {
        sendView.setUint8(i + j, jsonRequest.charCodeAt(j));
    }

    this.socket.send(sendView);

    this.isActive = true;
    if (this.mCnfVideoBufferTime > 0)
        this.decodeLoop();

};


WSSource.prototype.onClose = function() {
    this.logger.log("closed!");
    this.isActive = false;
    // ?????
    if (this.decoder.close() != 0) {
        this.logger.logError("close decoer");
    }
    var objData = {
        t: KWebSocket_Close
    };
    self.postMessage(objData);
};


WSSource.prototype.startRecving = function() {
    this.isActive = true;
    this.logger.log("start recv stream frame!");
    var objData = {
        ss: this.jsonRequest,
        at: "play"
    };
    //this.socket.send(JSON.stringify(objData));
};

WSSource.prototype.stopRecving = function() {
    this.isActive = false;
    this.socket.close();
    this.sessionState = 0;
    this.logger.log("stop recv stream frame!");
    var objData = {
        ss: this.jsonRequest,
        at: "stop"
    };
    //	this.socket.send(JSON.stringify(objData));

    this._mAudioBufferArray = [];
    this._mVideoBufferArray = [];
};


WSSource.prototype.playControl = function(action, offset) {
    if (!this.isActive) return false;

    this.mPlayConrolState = action;

    //if(action==1)	//暂停
    {
        var hwHeaderLen = 8;
        var jsonRequest = "{\"action\":\"3006\",\"payload\":{\"sessionID\":\"" + this.sessionObj.sessionId + "\",\"deviceID\":\"" + this.sessionObj.deviceId + "\",\"offset\":\"" + offset + "\",\"action\":\"" + action + "\"}}";
        var buffer = new ArrayBuffer(jsonRequest.length + hwHeaderLen);
        var sendView = new DataView(buffer);

        // add message header
        var i = 0;
        sendView.setInt8(i++, 0x48); //'H'
        sendView.setInt8(i++, 1); // version:1
        sendView.setInt16(i, 2, true); // action code: 2£¬little endian.  2-json request, 5-media data
        i += 2;
        sendView.setInt32(i, jsonRequest.length, true); // request json length£¬little endian
        i += 4;
        for (var j = 0; j < jsonRequest.length; j++) {
            sendView.setUint8(i + j, jsonRequest.charCodeAt(j));
        }

        this.socket.send(sendView);
    }
}
WSSource.prototype.sendFastRequest = function() {

    // Send howen json request
    //this.speed	= 1;	//播放速度 // 快进控制： {"action":"3006","payload":{"sessionID":"6","deviceID":"800801","offset":"2","action":"3"}}
    if (this.sessionObj.speed < 2 || this.speedContorlSend) return;

    this.playControl(3, this.sessionObj.speed);
    this.speedContorlSend = true;
    return;

  

};


WSSource.prototype.openAudio = function(isAudio) {
    this.decoder.openAudio(isAudio);
};
self.source = new WSSource;

self.onmessage = function(evt) {
    var rep = evt.data;
    switch (rep.t) {
        case KWebSocket_ConnectReq:
            self.source.connectServer(rep);
            break;
        case kInitDecoderReq:
            self.source.init();
            self.source.mCnfVideoBufferTime = rep.buff;
            break;
        case KWebSocket_StreamStart:
            self.source.startRecving();
            break;
        case KWebSocket_playControl:
            self.source.playControl(rep.d, rep.o);
            break;
        case KWebSocket_StreamStop:
            self.source.stopRecving();
            break;
        case KWebSocket_OpenAudio:
            self.source.openAudio(rep.d);
            break;
        case kAudioPCMData:
            self.source.putInPcmData(rep.u);
            break;
    }
};