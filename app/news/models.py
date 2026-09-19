from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.core.log import scrivi_log


@dataclass
class Article:
    title: str = ""
    link: str = ""
    summary: str = ""
    published: Optional[datetime] = None
    content: str = ""
    id: int = 0
    guid: str = ""
    source_url: str = ""
    source_name: str = ""
    category_id: Optional[int] = None
    category: str = ""
    is_read: bool = False
    full_text: str = ""

    def data_testo(self):
        try:
            if not self.published:
                return ""
            oggi = datetime.now().date()
            giorno = self.published.date()
            ora = self.published.strftime("%H:%M")
            if giorno == oggi:
                return f"oggi alle {ora}"
            if giorno == oggi - timedelta(days=1):
                return f"ieri alle {ora}"
            return self.published.strftime("%d/%m/%Y")
        except Exception as ex:
            scrivi_log("Article.data_testo", ex)
            return ""

    def label(self, mostra_fonte=True):
        try:
            parti = [self.title]
            if mostra_fonte and self.source_name:
                parti.append(self.source_name)
            data = self.data_testo()
            if data:
                parti.append(data)
            if not self.is_read:
                parti.append("non letto")
            return ", ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("Article.label", ex)
            return str(self.title)

    def chiave(self):
        try:
            return self.link or self.guid or f"{self.source_url}#{self.title}"
        except Exception as ex:
            scrivi_log("Article.chiave", ex)
            return str(self.title)
