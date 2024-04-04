class Global:
    def __init__(self):
        self.engine = None
        self.async_session_maker = None
        self.openai_client = None
        self.openai_gpt_model = None
        self.openai_embed_model = None
        self.openai_embed_dimensions = None
        self.openai_gpt_deployment = None
        self.openai_embed_deployment = None


global_storage = Global()
