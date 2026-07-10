import asyncio
import json
import logging
import os
import ssl
import websockets
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider

logger = logging.getLogger(__name__)


class MiniMaxTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        super().__init__(config)
        
        # MiniMax API 配置
        self.api_key = os.getenv("MINIMAX_API_KEY")
        if not self.api_key:
            raise ValueError("MiniMaxTTS: 环境变量 MINIMAX_API_KEY 未设置")
        
        self.model = getattr(config, 'model_name', None) or "speech-2.8-hd"
        self.voice_id = self.config.voice_name if self.config.voice_name else "male-qn-qingse"
        self.output_format = self.config.output_format if self.config.output_format else "mp3"
        
        # 音频设置
        self.sample_rate = 32000
        self.bitrate = 128000
        self.channel = 1
        
        # 语速设置
        self.speed = getattr(config, 'speed', None) or 1.0

    def text_to_speech(self, text: str, output_file_path: str, audio_tags=None):
        """
        调用 MiniMax TTS WebSocket API 并将返回的音频数据保存到指定路径
        """
        logger.info(f"正在调用 MiniMax TTS 接口 | 音色: {self.voice_id} | 模型: {self.model} | 文本长度: {len(text)}")
        
        try:
            # 运行异步 WebSocket 通信
            audio_data = asyncio.run(self._generate_audio(text))
            
            if audio_data:
                with open(output_file_path, "wb") as f:
                    f.write(audio_data)
                logger.info(f"音频成功生成并保存至: {output_file_path}")
            else:
                raise RuntimeError("MiniMax TTS 未返回音频数据")
                
        except Exception as e:
            logger.error(f"调用 MiniMax TTS 接口时发生异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise e

    async def _generate_audio(self, text: str) -> bytes:
        """异步生成音频数据"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        url = "wss://api.minimaxi.com/ws/v1/t2a_v2"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        try:
            async with websockets.connect(url, additional_headers=headers, ssl=ssl_context) as ws:
                # 等待连接成功
                connected = json.loads(await ws.recv())
                if connected.get("event") != "connected_success":
                    raise RuntimeError(f"MiniMax WebSocket 连接失败: {connected}")
                logger.info("MiniMax WebSocket 连接成功")
                
                # 发送任务开始请求
                start_msg = {
                    "event": "task_start",
                    "model": self.model,
                    "voice_setting": {
                        "voice_id": self.voice_id,
                        "speed": self.speed,
                        "vol": 1,
                        "pitch": 0,
                        "english_normalization": False
                    },
                    "audio_setting": {
                        "sample_rate": self.sample_rate,
                        "bitrate": self.bitrate,
                        "format": self.output_format,
                        "channel": self.channel
                    }
                }
                await ws.send(json.dumps(start_msg))
                response = json.loads(await ws.recv())
                
                if response.get("event") != "task_started":
                    raise RuntimeError(f"MiniMax 任务启动失败: {response}")
                logger.info("MiniMax 任务已启动")
                
                # 发送文本并接收音频
                await ws.send(json.dumps({
                    "event": "task_continue",
                    "text": text
                }))
                
                audio_data = b""
                chunk_counter = 0
                
                while True:
                    response = json.loads(await ws.recv())
                    
                    if "data" in response and "audio" in response["data"]:
                        audio = response["data"]["audio"]
                        if audio:
                            audio_bytes = bytes.fromhex(audio)
                            audio_data += audio_bytes
                            chunk_counter += 1
                    
                    if response.get("is_final"):
                        logger.info(f"MiniMax 音频合成完成: {chunk_counter} 个数据块")
                        break
                
                # 发送任务完成
                await ws.send(json.dumps({"event": "task_finish"}))
                
                return audio_data
                
        except Exception as e:
            logger.error(f"MiniMax WebSocket 通信异常: {e}")
            raise

    def get_break_string(self):
        return " @BRK#"

    def get_output_file_extension(self):
        return self.output_format

    def validate_config(self):
        """验证配置参数"""
        if not os.getenv("MINIMAX_API_KEY"):
            raise ValueError("MiniMaxTTS: 环境变量 MINIMAX_API_KEY 未设置")
        
        # 验证音色 ID 是否在支持列表中
        supported_voices = get_minimax_supported_voices()
        voice_ids = [v[0] for v in supported_voices]
        if self.config.voice_name and self.config.voice_name not in voice_ids:
            logger.warning(f"MiniMaxTTS: 音色 {self.config.voice_name} 可能不在官方推荐列表中，但仍将尝试使用")

    def estimate_cost(self, text: str) -> float:
        """估算成本（MiniMax 需要根据实际使用量计费）"""
        # MiniMax 按字符数计费，这里返回 0 表示需要用户自行确认
        return 0.0


def get_minimax_supported_models():
    """返回支持的模型"""
    return ["speech-2.8-hd", "speech-2.8-turbo"]


def get_minimax_supported_output_formats():
    """返回支持的输出格式"""
    return ["mp3", "wav", "flac", "pcm"]


def get_minimax_supported_voices():
    """返回支持的音色列表: [(voice_id, voice_name), ...]"""
    return [
        # 中文 (普通话) - 基础音色
        ("male-qn-qingse", "青涩青年音色"),
        ("male-qn-jingying", "精英青年音色"),
        ("male-qn-badao", "霸道青年音色"),
        ("male-qn-daxuesheng", "青年大学生音色"),
        ("female-shaonv", "少女音色"),
        ("female-yujie", "御姐音色"),
        ("female-chengshu", "成熟女性音色"),
        ("female-tianmei", "甜美女性音色"),
        # 中文 (普通话) - Beta 音色
        ("male-qn-qingse-jingpin", "青涩青年音色-beta"),
        ("male-qn-jingying-jingpin", "精英青年音色-beta"),
        ("male-qn-badao-jingpin", "霸道青年音色-beta"),
        ("male-qn-daxuesheng-jingpin", "青年大学生音色-beta"),
        ("female-shaonv-jingpin", "少女音色-beta"),
        ("female-yujie-jingpin", "御姐音色-beta"),
        ("female-chengshu-jingpin", "成熟女性音色-beta"),
        ("female-tianmei-jingpin", "甜美女性音色-beta"),
        # 中文 (普通话) - 特色音色
        ("clever_boy", "聪明男童"),
        ("cute_boy", "可爱男童"),
        ("lovely_girl", "萌萌女童"),
        ("cartoon_pig", "卡通猪小琪"),
        ("bingjiao_didi", "病娇弟弟"),
        ("junlang_nanyou", "俊朗男友"),
        ("chunzhen_xuedi", "纯真学弟"),
        ("lengdan_xiongzhang", "冷淡学长"),
        ("badao_shaoye", "霸道少爷"),
        ("tianxin_xiaoling", "甜心小玲"),
        ("qiaopi_mengmei", "俏皮萌妹"),
        ("wumei_yujie", "妩媚御姐"),
        ("diadia_xuemei", "嗲嗲学妹"),
        ("danya_xuejie", "淡雅学姐"),
        # 中文 (普通话) - 专业音色
        ("Chinese (Mandarin)_Reliable_Executive", "沉稳高管"),
        ("Chinese (Mandarin)_News_Anchor", "新闻女声"),
        ("Chinese (Mandarin)_Mature_Woman", "傲娇御姐"),
        ("Chinese (Mandarin)_Unrestrained_Young_Man", "不羁青年"),
        ("Arrogant_Miss", "嚣张小姐"),
        ("Robot_Armor", "机械战甲"),
        ("Chinese (Mandarin)_Kind-hearted_Antie", "热心大婶"),
        ("Chinese (Mandarin)_HK_Flight_Attendant", "港普空姐"),
        ("Chinese (Mandarin)_Humorous_Elder", "搞笑大爷"),
        ("Chinese (Mandarin)_Gentleman", "温润男声"),
        ("Chinese (Mandarin)_Warm_Bestie", "温暖闺蜜"),
        ("Chinese (Mandarin)_Male_Announcer", "播报男声"),
        ("Chinese (Mandarin)_Sweet_Lady", "甜美女声"),
        ("Chinese (Mandarin)_Southern_Young_Man", "南方小哥"),
        ("Chinese (Mandarin)_Wise_Women", "阅历姐姐"),
        ("Chinese (Mandarin)_Gentle_Youth", "温润青年"),
        ("Chinese (Mandarin)_Warm_Girl", "温暖少女"),
        ("Chinese (Mandarin)_Kind-hearted_Elder", "花甲奶奶"),
        ("Chinese (Mandarin)_Cute_Spirit", "憨憨萌兽"),
        ("Chinese (Mandarin)_Radio_Host", "电台男主播"),
        ("Chinese (Mandarin)_Lyrical_Voice", "抒情男声"),
        ("Chinese (Mandarin)_Straightforward_Boy", "率真弟弟"),
        ("Chinese (Mandarin)_Sincere_Adult", "真诚青年"),
        ("Chinese (Mandarin)_Gentle_Senior", "温柔学姐"),
        ("Chinese (Mandarin)_Stubborn_Friend", "嘴硬竹马"),
        ("Chinese (Mandarin)_Crisp_Girl", "清脆少女"),
        ("Chinese (Mandarin)_Pure-hearted_Boy", "清澈邻家弟弟"),
        ("Chinese (Mandarin)_Soft_Girl", "柔和少女"),
        # 中文 (粤语)
        ("Cantonese_ProfessionalHost（F)", "专业女主持"),
        ("Cantonese_GentleLady", "温柔女声"),
        ("Cantonese_ProfessionalHost（M)", "专业男主持"),
        ("Cantonese_PlayfulMan", "活泼男声"),
        ("Cantonese_CuteGirl", "可爱女孩"),
        ("Cantonese_KindWoman", "善良女声"),
        # 英文
        ("Santa_Claus", "Santa Claus"),
        ("Grinch", "Grinch"),
        ("Rudolph", "Rudolph"),
        ("Arnold", "Arnold"),
        ("Charming_Santa", "Charming Santa"),
        ("Charming_Lady", "Charming Lady"),
        ("Sweet_Girl", "Sweet Girl"),
        ("Cute_Elf", "Cute Elf"),
        ("Attractive_Girl", "Attractive Girl"),
        ("Serene_Woman", "Serene Woman"),
        ("English_Trustworthy_Man", "Trustworthy Man"),
        ("English_Graceful_Lady", "Graceful Lady"),
        ("English_Aussie_Bloke", "Aussie Bloke"),
        ("English_Whispering_girl", "Whispering girl"),
        ("English_Diligent_Man", "Diligent Man"),
        ("English_Gentle-voiced_man", "Gentle-voiced man"),
    ]


def get_minimax_voice_choices():
    """返回音色选择列表 (用于 UI 下拉框)"""
    voices = get_minimax_supported_voices()
    return [f"{voice_id} ({name})" for voice_id, name in voices]


def get_minimax_voice_id_from_choice(choice: str) -> str:
    """从 UI 选择中提取 voice_id"""
    if "(" in choice:
        return choice.split("(")[0].strip()
    return choice
