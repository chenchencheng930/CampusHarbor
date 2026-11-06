import re


class PrivacySanitizer:
    patterns = [
        re.compile(r"1[3-9]\d{9}"),
        re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
        re.compile(r"\b\d{17}[\dXx]\b"),
        re.compile(r"(?:我是|我叫)[^，。！？,!?\n]{2,40}(?=[，。！？,!?\n])"),
        re.compile(r"姓名(?:是|：|:)?[\u4e00-\u9fff·]{2,8}"),
        re.compile(r"\d{2,4}级[\u4e00-\u9fff·]{2,8}"),
        re.compile(r"[\u4e00-\u9fff]{2,20}(?:学院|系)(?:\d{2,4}级)?"),
        re.compile(r"\d{2,4}级"),
        re.compile(r"(?:宿舍|寝室)(?:楼|号楼)?[A-Za-z0-9\-栋室]{1,12}"),
    ]

    def sanitize(self, text: str) -> str:
        sanitized = text or ""
        for pattern in self.patterns:
            sanitized = pattern.sub("[已脱敏]", sanitized)
        return sanitized

