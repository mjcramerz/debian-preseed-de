"""Small in-memory index; fixed bounds, stable ranking and content snippets."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


def normalize(source: str) -> str:
    return unicodedata.normalize('NFKC', source).casefold()


def tokens(source: str) -> list[str]:
    return re.findall(r'\w+', normalize(source), re.UNICODE)[:64]


@dataclass(frozen=True)
class Result:
    id: str
    score: int
    snippet: str


class SearchIndex:
    def __init__(self, catalog):
        self.catalog = catalog
        self.documents = {}
        for article in catalog.articles.values():
            if article.error:
                continue
            counts = Counter()
            for value, weight in ((article.title, 20), (article.summary, 8), (' '.join(article.keywords), 12), (article.content, 1)):
                # Do not apply the query token limit to article contents.
                for token, count in Counter(re.findall(r'\w+', normalize(value))).items():
                    counts[token] += weight * min(count, 8)
            self.documents[article.id] = counts

    def search(self, query: str) -> list[Result]:
        words = list(dict.fromkeys(tokens(query[:200])))[:12]
        if not words:
            return []
        results = []
        for aid, counts in self.documents.items():
            scores = [sum(weight if token == word else max(1, weight // 3)
                          for token, weight in counts.items() if token.startswith(word)) for word in words]
            if not all(scores):
                continue
            article = self.catalog.articles[aid]
            score = sum(scores) + (100 if normalize(query) in normalize(article.title) else 0)
            source = article.content.replace('\n', ' ')
            positions = [normalize(source).find(word) for word in words]
            start = max(0, min((p for p in positions if p >= 0), default=0) - 50)
            snippet = ('…' if start else '') + source[start:start + 220] + ('…' if start + 220 < len(source) else '')
            results.append(Result(aid, score, snippet or article.summary))
        return sorted(results, key=lambda r: (-r.score, self.catalog.articles[r.id].order, r.id))[:100]
