class GeneralConfig:
    def __init__(self, args):
        # General arguments
        self.input_file = getattr(args, 'input_file', None)
        self.output_folder = getattr(args, 'output_folder', None)
        self.preview = getattr(args, 'preview', None)
        self.output_text = getattr(args, 'output_text', None)
        self.log = getattr(args, 'log', None)
        self.log_file = None
        self.no_prompt = getattr(args, 'no_prompt', None)
        self.worker_count = getattr(args, 'worker_count', None)
        self.use_pydub_merge = getattr(args, 'use_pydub_merge', None)

        # 统一质量核心首轮仅 MiMo；限制计算与重试，不使用费用预算。
        self.audio_core_enabled = getattr(args, 'audio_core_enabled', False)
        self.audio_core_repair = getattr(args, 'audio_core_repair', False)
        self.audio_core_max_english_wpm = getattr(args, 'audio_core_max_english_wpm', 300.0)
        self.audio_core_chunk_chars = getattr(args, 'audio_core_chunk_chars', 300)
        self.audio_core_max_requests = getattr(args, 'audio_core_max_requests', 1000)
        self.audio_core_max_repairs = getattr(args, 'audio_core_max_repairs', 24)
        self.audio_core_max_repair_characters = getattr(args, 'audio_core_max_repair_characters', None)
        self.audio_core_max_seconds = getattr(args, 'audio_core_max_seconds', 3600)
        self.audio_core_no_asr = getattr(args, 'audio_core_no_asr', False)
        self.audio_core_no_speaker = getattr(args, 'audio_core_no_speaker', False)
        self.audio_core_vad = getattr(args, 'audio_core_vad', False)
        self.audio_core_asr_model = getattr(args, 'audio_core_asr_model', None)
        self.audio_core_speaker_model = getattr(args, 'audio_core_speaker_model', None)
        self.audio_core_boundary_model = getattr(args, 'audio_core_boundary_model', None)
        self.audio_core_role_references = getattr(args, "audio_core_role_references", None)
        self.audio_core_tail_repeat_mode = getattr(args, 'audio_core_tail_repeat_mode', 'review')
        self.audio_core_casting = getattr(args, 'audio_core_casting', None)
        self.audio_core_reading_dictionary = getattr(args, 'audio_core_reading_dictionary', None)
        self.audio_core_transition_boundaries = getattr(args, 'audio_core_transition_boundaries', [])
        self.audio_core_transition_source_group = getattr(args, 'audio_core_transition_source_group', None)

        # Multi-role script mode. CLI stores a path; WebUI stores a parsed,
        # pickle-safe RoleScriptV1/V2 instance.
        self.role_script = getattr(args, 'role_script', None)
        self.voice_profile = getattr(args, 'voice_profile', None)
        self.allow_role_text_override = getattr(args, 'allow_role_text_override', False)
        self.allow_role_title_mismatch = getattr(args, 'allow_role_title_mismatch', False)
        self.allow_role_fallback = getattr(args, 'allow_role_fallback', False)
        self.role_quality_enabled = getattr(args, 'role_quality_enabled', False)
        self.role_quality_max_rate = getattr(args, 'role_quality_max_rate', 4.3)
        self.role_quality_deepseek_api_key = getattr(args, 'role_quality_deepseek_api_key', None)
        self.role_quality_deepseek_base_url = getattr(args, 'role_quality_deepseek_base_url', None)
        self.role_quality_deepseek_model = getattr(args, 'role_quality_deepseek_model', None)

        # Book parser specific arguments
        self.title_mode = getattr(args, 'title_mode', None)
        self.newline_mode = getattr(args, 'newline_mode', None)
        self.chapter_start = getattr(args, 'chapter_start', None)
        self.chapter_end = getattr(args, 'chapter_end', None)
        self.remove_endnotes = getattr(args, 'remove_endnotes', None)
        self.remove_reference_numbers = getattr(args, 'remove_reference_numbers', None)
        self.search_and_replace_file = getattr(args, 'search_and_replace_file', None)

        # TTS provider: common arguments
        self.tts = getattr(args, 'tts', None)
        self.language = getattr(args, 'language', None)
        self.voice_name = getattr(args, 'voice_name', None)
        self.output_format = getattr(args, 'output_format', None)
        self.model_name = getattr(args, 'model_name', None)

        # OpenAI specific arguments
        self.instructions = getattr(args, 'instructions', None)
        self.speed = getattr(args, 'speed', None)
        self.stream = getattr(args, 'stream', None)

        # TTS provider: Qwen & Edge TTS specific arguments
        self.break_duration = getattr(args, 'break_duration', None)

        # TTS provider: Edge specific arguments
        self.voice_rate = getattr(args, 'voice_rate', None)
        self.voice_volume = getattr(args, 'voice_volume', None)
        self.voice_pitch = getattr(args, 'voice_pitch', None)
        self.proxy = getattr(args, 'proxy', None)

        # TTS provider: Piper specific arguments
        self.piper_path = getattr(args, 'piper_path', None)
        self.piper_docker_image = getattr(args, 'piper_docker_image', None)
        self.piper_speaker = getattr(args, 'piper_speaker', None)
        self.piper_noise_scale = getattr(args, 'piper_noise_scale', None)
        self.piper_noise_w_scale = getattr(args, 'piper_noise_w_scale', None)
        self.piper_length_scale = getattr(args, 'piper_length_scale', None)
        self.piper_sentence_silence = getattr(args, 'piper_sentence_silence', None)

        # TTS provider: Chatterbox specific arguments
        self.chatterbox_device = getattr(args, 'chatterbox_device', None)
        self.chatterbox_reference_audio = getattr(args, 'chatterbox_reference_audio', None)
        self.chatterbox_exaggeration = getattr(args, 'chatterbox_exaggeration', None)
        self.chatterbox_cfg_weight = getattr(args, 'chatterbox_cfg_weight', None)
        self.chatterbox_speed = getattr(args, 'chatterbox_speed', None)

        # TTS provider: VoxCPM specific arguments
        self.voxcpm_device = getattr(args, 'voxcpm_device', None)
        self.voxcpm_mode = getattr(args, 'voxcpm_mode', None)
        self.voxcpm_voice = getattr(args, 'voxcpm_voice', None)
        self.voxcpm_voice_description = getattr(args, 'voxcpm_voice_description', None)
        self.voxcpm_voice_dir = getattr(args, 'voxcpm_voice_dir', None)
        self.voxcpm_regenerate_voice = getattr(args, 'voxcpm_regenerate_voice', None)
        self.voxcpm_reference_audio = getattr(args, 'voxcpm_reference_audio', None)
        self.voxcpm_reference_text = getattr(args, 'voxcpm_reference_text', None)
        self.voxcpm_auto_transcribe = getattr(args, 'voxcpm_auto_transcribe', None)
        self.voxcpm_denoise = getattr(args, 'voxcpm_denoise', None)
        self.voxcpm_normalize = getattr(args, 'voxcpm_normalize', None)
        self.voxcpm_cfg_value = getattr(args, 'voxcpm_cfg_value', None)
        self.voxcpm_inference_timesteps = getattr(args, 'voxcpm_inference_timesteps', None)
        self.voxcpm_speed = getattr(args, 'voxcpm_speed', None)
        self.voxcpm_chunk_chars = getattr(args, 'voxcpm_chunk_chars', None)
        self.voxcpm_optimize = getattr(args, 'voxcpm_optimize', None)
        self.voxcpm_seed = getattr(args, 'voxcpm_seed', None)

    def __str__(self):
        return ",\n".join(
            f"{key}={'[已隐藏]' if 'api_key' in key.lower() and value else value}"
            for key, value in self.__dict__.items()
        )
