import random
import re
# VOICE = {
#     "GREETING": [
#         "أهْلِينْ فِيكْ.. شُو بِتْحِبّْ تِطْلُبْ؟",
#         "نَوَّرْتْنا. شُو حابِبْ تُطْلُبْ اليُوْم؟"
#     ],

#     "ASK_ITEM": "شُو بِتْحِبّْ تِطْلُبْ؟",

#     "ITEM_FOUND": "تَمامْ... عِنَّا {item}",

#     "ASK_SIZE": "شُو الحَجِمْ؟ اصْغير، وَسَط، وَلّا اكْبِير؟",

#     "ASK_QUANTITY": "قَدّيش بِدَّك؟",

#     "ASK_NOTE": "بِدَّكْ مُلاحَظَة؟ اِحْكي، أَو قُولْ لا",

#     "CONFIRM": "تَمامْ. تَمّ الطَّلَب",

#     "NOT_FOUND": "مِش مَتْوَفِّرْ هادْ الصِّنفْ. بِدَّك إِشْي تانِي؟",

#     "INVALID": "مِش واضِحْ. مُمْكِنْ اتْعيد؟",

#     "NO_AUDIO": "الصَّوْتْ مِش جاهِز",

#     "THANKS": [
#         "مَشْكُورْ... جَاهْزِينْ بِأَيّْ وَقْت",
#         "تَمامْ. أَهْلًا فِيكْ بِأَيّْ وَقْت",
#         "وَلا يِهِمَّكْ. إِذا بِدَّكْ إِشْي أَنا مَوجودِة"
#     ],
# }

VOICE = {
    "GREETING": [
        "اهلا وسهلا فيك، شو بتحب تطلب؟",
        "نوّرتنا... شو حابب تاكل اليوم؟"
    ],

    "ASK_ITEM": "شو بتحب تطلب؟",

    "ITEM_FOUND": "تمام، عِنّا {item}",

    "ASK_SIZE": "شو الحجم؟ صغير، وسط، ولا كبير؟",

    "ASK_QUANTITY": "قديش بدك؟",

    "ASK_NOTE": "بدك ملاحظة؟ احكي، او قول لا",

    "CONFIRM": "تمام، تم الطلب",

    "NOT_FOUND": "مش متوفر هاد الصنف، بدك اشي تاني؟",

    "INVALID": "مش واضح، ممكن تعيد؟",

    "NO_AUDIO": "الصوت مش جاهز",

    "THANKS": [
        "يِسْلَمُوا، جاهزين بأي وقت",
        "تمام، اهلا فيك بأي وقت",
        "ولا يهمك، اذا بدك شي انا موجودة"
    ],
}



def pick(key):
    value = VOICE.get(key)

    if isinstance(value, list):
        return random.choice(value)

    return value


def number_to_arabic(n):
    words = {
        0: "صفر",
        1: "واحد",
        2: "اثنين",
        3: "ثلاثة",
        4: "أربعة",
        5: "خمسة",
        6: "ستة",
        7: "سبعة",
        8: "ثمانية",
        9: "تسعة",
        10: "عشرة",
        20: "عشرين",
        30: "ثلاثين",
        40: "أربعين",
        50: "خمسين",
        60: "ستين",
        70: "سبعين",
        80: "ثمانين",
        90: "تسعين",
    }

    try:
        n = int(n)
    except:
        return str(n)

    if n in words:
        return words[n]

    if 10 < n < 20:
        return str(n)

    if n < 100:
        tens = (n // 10) * 10
        ones = n % 10
        if ones == 0:
            return words[tens]
        return f"{words[ones]} و {words[tens]}"

    return str(n)




def normalize(text):
    text = (text or "").lower().strip()

    # ✅ إزالة الرموز (هاي أهم سطر)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", "", text)

    replacements = {
        "pizza": "بيتزا",
        "burger": "برجر",
        "cola": "كولا",
        "+": " مع ",
    }

    for source, replacement in replacements.items():
        text = text.replace(source, replacement)

    return " ".join(text.split())