class DummyStore:
    def get_all(self, ticker):
        return {}
feature_store = DummyStore()
