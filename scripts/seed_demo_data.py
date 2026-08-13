"""Bazani demo (test) ma'lumot bilan to'ldirish.

`app/models.py` dagi BARCHA jadvallar uchun mazmunli, o'zaro bog'langan
yozuvlar yaratadi: tibbiyot universiteti konteksti, o'zbekcha/ruscha matnlar.

Skript faqat QO'SHADI — hech qachon o'chirmaydi. Idempotent: qayta ishga
tushirilsa mavjud yozuvlarni topib o'tkazib yuboradi. `--suffix` bilan
mustaqil yangi to'plam yaratish mumkin.

Ishlatish:
    cd backend
    python3 scripts/seed_demo_data.py                  # tasdiq so'raydi
    python3 scripts/seed_demo_data.py --yes            # tasdiqsiz
    python3 scripts/seed_demo_data.py --students 20 --yes
    python3 scripts/seed_demo_data.py --suffix 2 --yes # ikkinchi to'plam
"""

import argparse
import asyncio
import os
import random
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from app.core import config  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Announcement,
    ApplicationStatus,
    AttendanceRecord,
    AttendanceStatus,
    ChatMessage,
    ClinicalArenaAttempt,
    ExamAttempt,
    ExamQuestion,
    ExamStatus,
    ExcuseStatus,
    FaqEntry,
    GroupChatMessage,
    Homework,
    HomeworkSubmission,
    KnowledgeChunk,
    LessonSchedule,
    MaterialType,
    MedicalTerm,
    NotificationLog,
    QuizAttempt,
    QuizAttemptStatus,
    QuizQuestion,
    RequestStatus,
    SavedItem,
    SavedItemType,
    SessionState,
    StudentApplication,
    StudentGrade,
    StudentGroup,
    StudentRequest,
    StudentSession,
    StudentTopicAccess,
    Subject,
    SubjectMaterial,
    Topic,
    TopicMaterial,
    TopicStatus,
    User,
    UserRole,
    utcnow,
)

DEMO_PASSWORD = "Demo12345"

# Takrorlanuvchi natija uchun qat'iy urug'.
rng = random.Random(20240513)


# ---------------------------------------------------------------------------
# Kontent: fanlar, mavzular, matnlar, savollar
# ---------------------------------------------------------------------------

SUBJECTS = [
    {
        "title": "Odam anatomiyasi",
        "description": (
            "Tana tuzilishi, a'zolar sistemasi va xalqaro anatomik "
            "nomenklatura asoslari. 12 modul."
        ),
        "materials": [
            ("pdf", "Anatomiya atlasi (1-qism)", "Skelet va mushaklar",
             "https://cdn.example.uz/demo/anatomiya-atlas-1.pdf"),
            ("video", "Yurak tuzilishi — video ma'ruza", "42 daqiqa",
             "https://video.example.uz/demo/yurak-tuzilishi"),
        ],
        "topics": [
            {
                "title": "Yurak-qon tomir sistemasi anatomiyasi",
                "description": "Yurak kameralari, klapanlar va yirik qon tomirlar.",
                "topic_type": "anatomiya",
                "video_url": "https://video.example.uz/demo/cor-anatomia",
                "leksika": (
                    "Yurak (lot. cor, yun. cardia) — ko'krak qafasining o'rta bo'shlig'ida, "
                    "ikki o'pka orasida joylashgan konussimon mushak a'zo. Uning massasi "
                    "voyaga yetgan odamda o'rtacha 250-350 gramm bo'ladi va u sutkasiga "
                    "taxminan 7000 litr qon haydaydi.\n\n"
                    "Yurak to'rt kamerali: o'ng bo'lmacha (atrium dextrum), o'ng qorincha "
                    "(ventriculus dexter), chap bo'lmacha (atrium sinistrum) va chap qorincha "
                    "(ventriculus sinister). Chap qorincha devori o'ngnikidan uch baravar "
                    "qalin, chunki u qonni katta qon aylanish doirasiga haydaydi.\n\n"
                    "Klapanlar qonning bir tomonlama harakatini ta'minlaydi: uch tavaqali "
                    "(valva tricuspidalis) o'ng tomonda, ikki tavaqali yoki mitral klapan "
                    "(valva mitralis) chap tomonda joylashgan. Yarim oysimon klapanlar aorta "
                    "va o'pka arteriyasi og'zida turadi."
                ),
                "grammatika": (
                    "Anatomik atamalarda lotin tilining birinchi va ikkinchi turlanishi "
                    "ko'p uchraydi: arteria — arteriae, ventriculus — ventriculi. Qaratqich "
                    "kelishigi (genetivus) a'zoning tegishliligini bildiradi: valva aortae — "
                    "aorta klapani.\n\n"
                    "Sifatlar otdan keyin keladi va u bilan rod, son, kelishikda moslashadi: "
                    "atrium dextrum (o'ng bo'lmacha), vena cava superior (yuqori kavak vena). "
                    "Rus tilida esa sifat otdan oldin turadi: правое предсердие."
                ),
            },
            {
                "title": "Suyak va mushak sistemasi",
                "description": "Skelet bo'limlari, bo'g'imlar turlari va asosiy mushak guruhlari.",
                "topic_type": "anatomiya",
                "video_url": "https://video.example.uz/demo/systema-skeletalis",
                "leksika": (
                    "Odam skeleti 206 ta suyakdan iborat bo'lib, o'q skeleti (skeleton axiale) "
                    "va qo'shimcha skelet (skeleton appendiculare) ga bo'linadi. O'q skeletiga "
                    "kalla suyaklari, umurtqa pog'onasi va ko'krak qafasi kiradi.\n\n"
                    "Umurtqa pog'onasi (columna vertebralis) 33-34 ta umurtqadan tashkil topgan: "
                    "7 ta bo'yin, 12 ta ko'krak, 5 ta bel, 5 ta dumg'aza va 4-5 ta dum umurtqasi. "
                    "Uning fiziologik egriliklari — lordoz va kifoz — yurishda zarbani yumshatadi.\n\n"
                    "Skelet mushaklari ko'ndalang-targ'il to'qimadan tuzilgan va ixtiyoriy "
                    "boshqariladi. Har bir mushakda bosh (caput), qorincha (venter) va pay "
                    "(tendo) qismlari ajratiladi."
                ),
                "grammatika": (
                    "Ko'plik shakli lotin tilida turlanishga bog'liq: vertebra — vertebrae, "
                    "musculus — musculi, os — ossa. Tibbiy hujjatlarda ko'pincha qisqartma "
                    "ishlatiladi: m. biceps brachii, a. femoralis.\n\n"
                    "Rus tilida a'zo nomlari bilan predlogli konstruksiyalar muhim: боль в "
                    "поясничном отделе позвоночника — umurtqaning bel qismidagi og'riq."
                ),
            },
        ],
        "questions": [
            ("Yurakning chap qorinchasi qonni qaysi qon tomirga haydaydi?",
             {"A": "O'pka arteriyasiga", "B": "Aortaga", "C": "Yuqori kavak venaga",
              "D": "Koronar sinusga"},
             "B", "Chap qorincha qonni aortaga, ya'ni katta qon aylanish doirasiga haydaydi."),
            ("Mitral klapan yurakning qaysi qismlari orasida joylashgan?",
             {"A": "O'ng bo'lmacha va o'ng qorincha", "B": "Chap bo'lmacha va chap qorincha",
              "C": "Chap qorincha va aorta", "D": "O'ng qorincha va o'pka arteriyasi"},
             "B", "Mitral (ikki tavaqali) klapan chap bo'lmacha bilan chap qorincha orasida."),
            ("Voyaga yetgan odam skeletida nechta suyak bor?",
             {"A": "180 ta", "B": "206 ta", "C": "230 ta", "D": "270 ta"},
             "B", "Voyaga yetgan odamda 206 ta suyak bo'ladi."),
            ("Umurtqa pog'onasining bel qismida nechta umurtqa bor?",
             {"A": "5 ta", "B": "7 ta", "C": "12 ta", "D": "4 ta"},
             "A", "Bel qismida (pars lumbalis) 5 ta umurtqa joylashgan."),
            ("«Vena cava superior» atamasi qanday tarjima qilinadi?",
             {"A": "Pastki kavak vena", "B": "Yuqori kavak vena", "C": "O'pka venasi",
              "D": "Bo'yinturuq venasi"},
             "B", "Superior — yuqori, cava — kavak, ya'ni yuqori kavak vena."),
            ("Mushakning payi lotin tilida qanday ataladi?",
             {"A": "Caput", "B": "Venter", "C": "Tendo", "D": "Fascia"},
             "C", "Pay — tendo; caput — bosh, venter — qorincha."),
        ],
    },
    {
        "title": "Normal fiziologiya",
        "description": (
            "Sog'lom organizm funksiyalari: qon aylanish, nafas, hazm va nerv "
            "boshqaruvi. 10 modul."
        ),
        "materials": [
            ("pdf", "Fiziologiya bo'yicha amaliy mashg'ulotlar", "Laboratoriya daftari",
             "https://cdn.example.uz/demo/fiziologiya-praktikum.pdf"),
            ("link", "Interaktiv EKG simulyatori", "Onlayn resurs",
             "https://sim.example.uz/demo/ekg"),
        ],
        "topics": [
            {
                "title": "Qon aylanish fiziologiyasi",
                "description": "Yurak sikli, arterial bosim va uning boshqarilishi.",
                "topic_type": "fiziologiya",
                "video_url": "https://video.example.uz/demo/cardiac-cycle",
                "leksika": (
                    "Yurak sikli — bo'lmachalar va qorinchalarning ketma-ket qisqarishi va "
                    "bo'shashishidan iborat takroriy jarayon. Tinch holatda u 0,8 soniya davom "
                    "etadi: sistola 0,3 s, diastola 0,5 s.\n\n"
                    "Arterial bosim ikki ko'rsatkich bilan ifodalanadi: sistolik (norma 110-130 "
                    "mm sim. ust.) va diastolik (70-85 mm sim. ust.). Ularning farqi puls "
                    "bosimi deb ataladi va odatda 40-50 mm sim. ustuniga teng.\n\n"
                    "Qon bosimi bosim retseptorlari (barorseptorlar), simpatik va parasimpatik "
                    "nerv tizimi hamda renin-angiotenzin-aldosteron tizimi orqali boshqariladi. "
                    "Qisqa muddatli boshqaruv nerv, uzoq muddatlisi gumoral yo'l bilan amalga oshadi."
                ),
                "grammatika": (
                    "Fiziologik jarayonlar ko'pincha majhul nisbatda bayon qilinadi: «bosim "
                    "barorseptorlar orqali boshqariladi». Rus tilida bunga qaytim fe'llari mos "
                    "keladi: давление регулируется барорецепторами.\n\n"
                    "O'lchov birliklari doim raqamdan keyin va qisqartirilgan holda yoziladi: "
                    "120/80 мм рт. ст., 72 уд/мин."
                ),
            },
            {
                "title": "Nafas olish fiziologiyasi",
                "description": "O'pka ventilyatsiyasi, gaz almashinuvi va nafas markazi.",
                "topic_type": "fiziologiya",
                "video_url": "https://video.example.uz/demo/respiratio",
                "leksika": (
                    "Tashqi nafas — atmosfera havosi bilan alveolalar orasidagi gaz almashinuvi. "
                    "Tinch holatda bir nafas hajmi (dixatelniy obyom) 500 ml ni tashkil qiladi, "
                    "nafas soni esa daqiqasiga 12-18 marta.\n\n"
                    "O'pkaning tiriklik sig'imi (JEL) o'rtacha 3,5-5 litr bo'lib, spirometriya "
                    "yordamida o'lchanadi. Bu ko'rsatkich yosh, jins va jismoniy tayyorgarlikka "
                    "bog'liq holda o'zgaradi.\n\n"
                    "Nafas markazi uzunchoq miyada joylashgan va qondagi CO2 miqdoriga eng sezgir. "
                    "Giperkapniya nafasni tezlashtiradi, gipokapniya esa apnoega olib kelishi mumkin."
                ),
                "grammatika": (
                    "Tibbiy matnda «-logiya», «-metriya», «-grafiya» qo'shimchalari usul va fan "
                    "nomini yasaydi: spirometriya — nafas hajmini o'lchash, kapnografiya — CO2 "
                    "ni qayd etish.\n\n"
                    "Grekcha prefikslar miqdorni bildiradi: gipo- (kam), giper- (ko'p), a-/an- "
                    "(yo'qlik). Shunga ko'ra gipoksiya — kislorod yetishmovchiligi."
                ),
            },
        ],
        "questions": [
            ("Tinch holatda yurak siklining davomiyligi qancha?",
             {"A": "0,4 soniya", "B": "0,8 soniya", "C": "1,2 soniya", "D": "2,0 soniya"},
             "B", "Normal yurak urish tezligida sikl 0,8 soniya davom etadi."),
            ("Puls bosimi qanday hisoblanadi?",
             {"A": "Sistolik + diastolik", "B": "Sistolik - diastolik",
              "C": "Diastolik / 2", "D": "Sistolik x 2"},
             "B", "Puls bosimi = sistolik bosim - diastolik bosim."),
            ("Tinch holatda bir nafas hajmi qancha?",
             {"A": "150 ml", "B": "500 ml", "C": "1200 ml", "D": "3000 ml"},
             "B", "Dixatelniy obyom taxminan 500 ml ni tashkil qiladi."),
            ("Nafas markazi qayerda joylashgan?",
             {"A": "Po'stloqda", "B": "Gipotalamusda", "C": "Uzunchoq miyada", "D": "Miyachada"},
             "C", "Nafas markazi uzunchoq miyada (medulla oblongata) joylashgan."),
            ("Nafas markazi eng avvalo qaysi omilga javob beradi?",
             {"A": "Qondagi CO2 miqdoriga", "B": "Tana haroratiga",
              "C": "Qon glyukozasiga", "D": "Arterial bosimga"},
             "A", "Nafas markazi qondagi karbonat angidrid darajasiga eng sezgir."),
            ("«Gipoksiya» atamasi nimani bildiradi?",
             {"A": "Kislorod ortiqchaligi", "B": "Kislorod yetishmovchiligi",
              "C": "Qand yetishmovchiligi", "D": "Bosim pasayishi"},
             "B", "Gipo- (kam) + oxys (kislorod) — kislorod yetishmovchiligi."),
        ],
    },
    {
        "title": "Farmakologiya",
        "description": (
            "Dori vositalarining ta'sir mexanizmi, dozalash va retsept yozish. "
            "15 modul."
        ),
        "materials": [
            ("pdf", "Retseptlar to'plami", "Namunalar bilan",
             "https://cdn.example.uz/demo/retseptlar.pdf"),
            ("doc", "Antibiotiklar klassifikatsiyasi", "Jadval",
             "https://cdn.example.uz/demo/antibiotiklar.docx"),
        ],
        "topics": [
            {
                "title": "Antibiotiklar farmakologiyasi",
                "description": "Beta-laktamlar, makrolidlar va rezistentlik muammosi.",
                "topic_type": "farmakologiya",
                "video_url": "https://video.example.uz/demo/antibiotica",
                "leksika": (
                    "Antibiotiklar ta'sir mexanizmiga ko'ra guruhlarga bo'linadi: hujayra "
                    "devori sintezini buzuvchilar (penitsillinlar, sefalosporinlar), oqsil "
                    "sintezini to'xtatuvchilar (makrolidlar, tetratsiklinlar) va nuklein "
                    "kislotalarga ta'sir qiluvchilar (ftorxinolonlar).\n\n"
                    "Beta-laktam antibiotiklar bakteriya devoridagi peptidoglikan sintezini "
                    "to'xtatadi. Ularning asosiy kamchiligi — beta-laktamaza fermentlari "
                    "tomonidan parchalanishi; shu sababli klavulan kislota bilan birga beriladi.\n\n"
                    "Antibiotikorezistentlik — XXI asrning global muammosi. Uning oldini olish "
                    "uchun antibiotik faqat ko'rsatma bo'yicha, to'liq kurs davomida va yetarli "
                    "dozada buyuriladi."
                ),
                "grammatika": (
                    "Retseptda dori nomi lotin tilida qaratqich kelishigida yoziladi: "
                    "Rp.: Amoxicillini 0,5. Miqdor grammda, vergul bilan ko'rsatiladi.\n\n"
                    "Buyruq shakllari retseptning ajralmas qismi: Da tales doses numero 20 "
                    "(shunday dozadan 20 ta ber), Signa (belgila)."
                ),
            },
            {
                "title": "Retsept yozish qoidalari",
                "description": "Retsept blankasi tuzilishi, lotincha qisqartmalar va xatolar.",
                "topic_type": "farmakologiya",
                "video_url": "https://video.example.uz/demo/praescriptio",
                "leksika": (
                    "Retsept — shifokorning dorixonaga yozma murojaati bo'lib, yuridik hujjat "
                    "hisoblanadi. U inscriptio, invocatio, designatio materiarum, subscriptio "
                    "va signatura qismlaridan iborat.\n\n"
                    "Dori shakllari: tabuletta (tabletka), capsula (kapsula), solutio (eritma), "
                    "unguentum (malham), suppositoria (shamcha), pulvis (kukun). Har bir shakl "
                    "o'z yozilish tartibiga ega.\n\n"
                    "Eng ko'p uchraydigan xatolar: dozani noto'g'ri ko'rsatish, signaturani "
                    "bemor tushunmaydigan tilda yozish va shifokor imzosini qo'ymaslik."
                ),
                "grammatika": (
                    "«Recipe» (ol) — buyruq maylidagi fe'l, Rp. deb qisqartiriladi. Undan keyin "
                    "dori nomi doim genetivus (qaratqich) kelishigida keladi.\n\n"
                    "Signatura bemor tilida yoziladi: «Kuniga 3 mahal 1 tabletkadan ovqatdan "
                    "keyin». Rus tilida: по 1 таблетке 3 раза в день после еды."
                ),
            },
        ],
        "questions": [
            ("Beta-laktam antibiotiklar bakteriyaning qaysi tuzilmasiga ta'sir qiladi?",
             {"A": "Hujayra devoriga", "B": "Ribosomaga", "C": "DNK-girazaga",
              "D": "Hujayra membranasiga"},
             "A", "Beta-laktamlar peptidoglikan, ya'ni hujayra devori sintezini to'xtatadi."),
            ("Klavulan kislota nima uchun qo'shiladi?",
             {"A": "Ta'mni yaxshilash uchun", "B": "Beta-laktamazani bloklash uchun",
              "C": "So'rilishni sekinlashtirish uchun", "D": "Og'riqni qoldirish uchun"},
             "B", "Klavulan kislota beta-laktamaza fermentini ingibirlaydi."),
            ("Makrolidlar ta'sir mexanizmi qanday?",
             {"A": "Hujayra devori sintezini buzadi", "B": "Oqsil sintezini to'xtatadi",
              "C": "Folat sintezini buzadi", "D": "Membranani teshadi"},
             "B", "Makrolidlar 50S ribosoma subbirligiga bog'lanib oqsil sintezini to'xtatadi."),
            ("Retseptdagi «Rp.» qisqartmasi nimani bildiradi?",
             {"A": "Recipe — ol", "B": "Repete — takrorla", "C": "Rapide — tez",
              "D": "Ratio — nisbat"},
             "A", "Rp. — Recipe, ya'ni «ol» degan buyruq shakli."),
            ("«D.t.d. N. 20» yozuvi nimani anglatadi?",
             {"A": "20 kun ichida ber", "B": "Shunday dozadan 20 ta ber",
              "C": "20 mg dan ber", "D": "20 marta takrorla"},
             "B", "Da tales doses numero 20 — shunday dozadan 20 ta ber."),
            ("Malham dori shakli lotin tilida qanday ataladi?",
             {"A": "Solutio", "B": "Pulvis", "C": "Unguentum", "D": "Suppositoria"},
             "C", "Unguentum — malham."),
        ],
    },
    {
        "title": "Klinik rus tili",
        "description": (
            "Bemor bilan muloqot, anamnez yig'ish va tibbiy hujjat yuritish "
            "uchun rus tili. 8 modul."
        ),
        "materials": [
            ("pdf", "Klinik dialoglar to'plami", "50 ta namuna",
             "https://cdn.example.uz/demo/klinik-dialoglar.pdf"),
            ("audio", "Bemor shikoyatlari — audio mashqlar", "30 daqiqa",
             "https://cdn.example.uz/demo/shikoyatlar.mp3"),
        ],
        "topics": [
            {
                "title": "Bemor bilan suhbat (anamnez)",
                "description": "Shikoyatlarni so'rash, anamnez morbi va anamnez vitae.",
                "topic_type": "leksika",
                "video_url": "https://video.example.uz/demo/anamnesis",
                "leksika": (
                    "Suhbat salomlashish va o'zini tanishtirish bilan boshlanadi: "
                    "«Здравствуйте! Меня зовут доктор Каримов. На что вы жалуетесь?» — "
                    "Assalomu alaykum! Men doktor Karimovman. Nimadan shikoyat qilyapsiz?\n\n"
                    "Asosiy shikoyat savollari: Где болит? (Qayeri og'riyapti?), Как давно? "
                    "(Qachondan beri?), Боль острая или тупая? (Og'riq o'tkirmi yoki xiramimi?), "
                    "Что усиливает боль? (Og'riqni nima kuchaytiradi?).\n\n"
                    "Anamnez vitae bosqichida turmush sharoiti, kasbi, yomon odatlari va irsiy "
                    "kasalliklar aniqlanadi: «Курите ли вы?», «Были ли в семье случаи диабета?»"
                ),
                "grammatika": (
                    "Og'riq haqida gapirganda «болит / болят» fe'li va predlogli konstruksiya "
                    "ishlatiladi: у меня болит голова, у пациента болят суставы.\n\n"
                    "Vaqtni bildirishda «с» + qaratqich kelishigi qo'llanadi: боль беспокоит с "
                    "понедельника — og'riq dushanbadan beri bezovta qilmoqda."
                ),
            },
            {
                "title": "Shifokor ko'rigi: tana a'zolari",
                "description": "Ko'rik paytidagi buyruqlar va a'zolar nomi.",
                "topic_type": "leksika",
                "video_url": "https://video.example.uz/demo/examinatio",
                "leksika": (
                    "Ko'rik paytida qo'llaniladigan buyruqlar: «Разденьтесь до пояса» "
                    "(Belgacha yechining), «Сделайте глубокий вдох» (Chuqur nafas oling), "
                    "«Задержите дыхание» (Nafasingizni ushlab turing).\n\n"
                    "Asosiy a'zolar: сердце — yurak, лёгкие — o'pka, печень — jigar, почки — "
                    "buyraklar, желудок — oshqozon, селезёнка — taloq, кишечник — ichak.\n\n"
                    "Ko'rik natijasi hujjatda qayd etiladi: «Кожные покровы чистые, дыхание "
                    "везикулярное, тоны сердца ясные, ритмичные» — teri toza, nafas vezikulyar, "
                    "yurak tonlari aniq va ritmik."
                ),
                "grammatika": (
                    "Buyruq mayli ko'plik shakli hurmat ma'nosini beradi va bemorga doim shu "
                    "shaklda murojaat qilinadi: сделайте, повернитесь, покажите.\n\n"
                    "Inkor buyruq nomukammal nisbatda yasaladi: «Не двигайтесь», «Не "
                    "разговаривайте во время осмотра»."
                ),
            },
        ],
        "questions": [
            ("«На что вы жалуетесь?» iborasi qanday tarjima qilinadi?",
             {"A": "Qayerda yashaysiz?", "B": "Nimadan shikoyat qilyapsiz?",
              "C": "Necha yoshdasiz?", "D": "Kim yubordi?"},
             "B", "Bu shifokorning birinchi standart savoli — shikoyatni aniqlash."),
            ("«Сделайте глубокий вдох» buyrug'i nimani anglatadi?",
             {"A": "Nafasni ushlang", "B": "Chuqur nafas oling", "C": "Yoting",
              "D": "O'giriling"},
             "B", "Vdox — nafas olish, glubokiy — chuqur."),
            ("«Печень» so'zining o'zbekcha tarjimasi qaysi?",
             {"A": "Buyrak", "B": "Taloq", "C": "Jigar", "D": "O'pka"},
             "C", "Печень — jigar."),
            ("Bemorga murojaat qilishda qaysi shakl to'g'ri?",
             {"A": "Сделай", "B": "Сделайте", "C": "Делать", "D": "Сделал"},
             "B", "Hurmat ma'nosidagi ko'plik buyruq shakli ishlatiladi."),
            ("«Боль беспокоит с понедельника» gapida «с» predlogi nimani bildiradi?",
             {"A": "Sababni", "B": "Vaqt boshlanishini", "C": "Joyni", "D": "Maqsadni"},
             "B", "«с» + qaratqich kelishigi harakat boshlangan vaqtni bildiradi."),
            ("«Тоны сердца ясные, ритмичные» xulosasi nimani anglatadi?",
             {"A": "Yurak tonlari aniq va ritmik", "B": "Nafas qisilgan",
              "C": "Teri quruq", "D": "Bosim yuqori"},
             "A", "Bu normal yurak auskultatsiyasi tavsifi."),
        ],
    },
]

# Demo lug'at — `seed_dictionary.py` dagi so'zlar bilan kesishmaydi.
TERMS = [
    ("Почка", "[п`очка]", "жен.р. (feminine)", "Buyrak", "Anatomiya",
     "Qonni filtrlab siydik hosil qiluvchi juft a'zo.",
     "Правая почка расположена чуть ниже левой.",
     "O'ng buyrak chap buyrakdan biroz pastroqda joylashgan."),
    ("Селезёнка", "[сил'из'`онка]", "жен.р. (feminine)", "Taloq", "Anatomiya",
     "Immun tizim va qon depolash bilan bog'liq a'zo.",
     "При травме живота возможен разрыв селезёнки.",
     "Qorin jarohatida taloqning yorilishi ehtimoli bor."),
    ("Кашель", "[к`ашыл']", "муж.р. (masculine)", "Yo'tal", "Terapiya",
     "Nafas yo'llarini tozalashga qaratilgan refleks.",
     "Сухой кашель беспокоит больного по ночам.",
     "Quruq yo'tal bemorni kechalari bezovta qiladi."),
    ("Температура", "[тимпир`атура]", "жен.р. (feminine)", "Harorat", "Terapiya",
     "Tana issiqligi darajasi, normada 36,6 °C.",
     "Температура держится третий день на уровне 38 градусов.",
     "Harorat uchinchi kun 38 daraja atrofida turibdi."),
    ("Наркоз", "[нарк`ос]", "муж.р. (masculine)", "Narkoz", "Jarrohlik",
     "Operatsiya davomida og'riqsizlantiruvchi sun'iy uyqu.",
     "Операция проводится под общим наркозом.",
     "Operatsiya umumiy narkoz ostida o'tkaziladi."),
    ("Шов", "[шоф]", "муж.р. (masculine)", "Chok", "Jarrohlik",
     "Jarohat yoki kesma chetlarini birlashtirish usuli.",
     "Швы снимают на седьмые сутки после операции.",
     "Choklar operatsiyadan keyingi yettinchi kuni olinadi."),
    ("Прививка", "[прив`ифка]", "жен.р. (feminine)", "Emlash", "Profilaktika",
     "Yuqumli kasallikka qarshi immunitet hosil qilish.",
     "Прививка от гриппа делается осенью.",
     "Grippga qarshi emlash kuzda qilinadi."),
    ("Анализ крови", "[ан`ализ кр`ови]", "муж.р. (masculine)", "Qon tahlili", "Diagnostika",
     "Qon tarkibini laboratoriya sharoitida tekshirish.",
     "Общий анализ крови сдают натощак.",
     "Umumiy qon tahlili och qoringa topshiriladi."),
]

FAQS = [
    ("davomat", "Davomat foizim qayerda ko'rinadi?",
     "Profil > Davomat bo'limida har bir fan kesimida foiz va qoldirilgan "
     "darslar ro'yxati ko'rsatiladi.", 10),
    ("davomat", "Darsni sababli qoldirgan bo'lsam nima qilaman?",
     "Davomat bo'limidan tegishli darsni tanlab «Sabab yuborish» tugmasini "
     "bosing va ma'lumotnomani biriktiring. Ustoz ko'rib chiqadi.", 20),
    ("imtihon", "Imtihonni yarim yo'lda to'xtatsam, davom ettira olamanmi?",
     "Ha. Imtihon vaqti tugamagan bo'lsa, ilovaga qayta kirganingizda "
     "urinish o'sha joyidan davom etadi.", 30),
    ("imtihon", "Imtihon savollari qayerdan olinadi?",
     "Savollar siz tanlagan fanning faol mavzulari materiallari asosida "
     "avtomatik shakllantiriladi.", 40),
    ("test", "Test natijam ustozga yuboriladimi?",
     "Ha, yakunlangan test hisobot sifatida mavzu muallifiga ko'rinadi.", 50),
    ("materiallar", "Mavzuni keyinroq o'qish uchun saqlab qo'ysam bo'ladimi?",
     "Mavzu, material yoki termin yonidagi belgini bosing — u «Saqlanganlar» "
     "bo'limiga tushadi.", 60),
]

ANNOUNCEMENTS = [
    ("Kuzgi semestr imtihon jadvali e'lon qilindi", "imtihon",
     "Hurmatli talabalar! Kuzgi semestr yakuniy imtihonlari 20-dekabrdan "
     "boshlanadi. To'liq jadval dekanat va ilovaning «Jadval» bo'limida "
     "joylashtirildi. Imtihonga ruxsatnoma olish uchun davomat 75% dan kam "
     "bo'lmasligi kerak."),
    ("Anatomiya muzeyiga ekskursiya", "tadbir",
     "Payshanba kuni soat 14:00 da 1-kurs talabalari uchun anatomiya "
     "muzeyiga ekskursiya tashkil etiladi. Yig'ilish joyi — asosiy bino "
     "kirish qismi. Xalat va almashtiriladigan poyabzal majburiy."),
    ("Kutubxona ish tartibi o'zgardi", "umumiy",
     "Kutubxona endi dushanbadan shanbagacha 08:30 dan 19:00 gacha ishlaydi. "
     "Elektron katalogdan foydalanish uchun talabalik ID raqamingiz kerak."),
    ("Grippga qarshi bepul emlash", "sogliq",
     "Universitet poliklinikasida barcha talabalar uchun grippga qarshi "
     "bepul emlash o'tkazilmoqda. Emlash 3-qavat, 312-xonada, 09:00-15:00 "
     "oralig'ida amalga oshiriladi."),
    ("Ilmiy to'garaklarga qabul", "ilmiy",
     "Kardiologiya, farmakologiya va klinik lingvistika to'garaklariga "
     "yangi a'zolar qabul qilinmoqda. Ariza topshirish muddati — shu oyning "
     "oxirigacha."),
]

CASE_SCENARIOS = [
    "O'tkir ko'krak og'rig'i bilan murojaat qilgan 54 yoshli bemor",
    "Uzoq davom etgan yo'tal va isitma: differensial tashxis",
    "Qorin o'ng pastki sohasidagi o'tkir og'riq",
    "Bosh og'rig'i va ko'rish xiralashuvi bilan kelgan bemor",
]

DUEL_OPPONENTS = ["Dilshod A.", "Malika R.", "Sardor N.", "Nigora T."]

HOMEWORKS = [
    ("Yurak kameralarini chizib, nomlang",
     "Daftaringizda yurakning frontal kesimini chizing va to'rt kamera, "
     "klapanlar hamda yirik qon tomirlarni lotincha nomlari bilan belgilang. "
     "Rasmni suratga olib yuklang."),
    ("Arterial bosimni o'lchash bo'yicha hisobot",
     "Uch kun davomida ertalab va kechqurun arterial bosimni o'lchab, "
     "jadval ko'rinishida yozing. Natijalarga qisqacha izoh bering."),
    ("Amoksitsillin uchun retsept yozing",
     "500 mg li amoksitsillin tabletkasi uchun to'liq lotincha retsept "
     "yozing: Rp., D.t.d., S. qismlari bilan."),
    ("Bemor bilan dialog tuzing",
     "Ko'krak og'rig'idan shikoyat qilgan bemor bilan rus tilida 10 "
     "replikadan iborat dialog tuzing va uni yozma topshiring."),
]

REQUESTS = [
    ("ma'lumotnoma", "Talabalik haqida ma'lumotnoma kerak",
     "Assalomu alaykum. Harbiy komissariatga taqdim etish uchun talabalik "
     "haqida ma'lumotnoma kerak edi. Iltimos, tayyorlab bersangiz.",
     RequestStatus.resolved,
     "Ma'lumotnoma tayyor, dekanat 204-xonasidan olib ketishingiz mumkin."),
    ("ruxsat", "Konferensiya sababli darsdan ruxsat",
     "15-noyabr kuni Toshkentdagi ilmiy konferensiyada ma'ruza qilaman. "
     "Shu kunlik darslardan ruxsat so'rayman.",
     RequestStatus.in_progress, None),
    ("texnik", "Ilovaga kira olmayapman",
     "Parolni to'g'ri kiritsam ham «login yoki parol xato» deb chiqmoqda. "
     "Yordam bering, iltimos.",
     RequestStatus.pending, None),
    ("akademik", "Fanni qayta topshirish",
     "Farmakologiya fanidan oraliq nazoratni kasallik sababli topshira "
     "olmadim. Qayta topshirish imkoni bormi?",
     RequestStatus.rejected,
     "Qayta topshirish uchun ariza muddati o'tib ketgan. Keyingi semestrda "
     "murojaat qiling."),
]

STUDENT_NAMES = [
    "Aziza Karimova", "Bekzod Rahimov", "Dilnoza Tursunova", "Eldor Sobirov",
    "Feruza Yo'ldosheva", "G'ayrat Nazarov", "Hilola Ergasheva", "Islom Qodirov",
    "Jasur Ochilov", "Kamola Sattorova", "Laziz Mirzayev", "Madina Umarova",
    "Nodir Halimov", "Ozoda Rustamova", "Po'lat Jo'rayev", "Qunduz Asadova",
    "Rustam Bekmurodov", "Sevara Xolmatova", "Temur Yusupov", "Umida Alimova",
]

EMPLOYEES = [
    {
        "suffix": "ustoz1",
        "full_name": "Nodira Alimovna Xolmatova",
        "department": "Odam anatomiyasi kafedrasi",
        "degree": "t.f.n., dotsent",
        "bio": "20 yillik pedagogik tajriba. Yurak-qon tomir anatomiyasi "
               "bo'yicha 30 dan ortiq ilmiy maqola muallifi.",
        "phone": "+998 90 111 22 33",
    },
    {
        "suffix": "ustoz2",
        "full_name": "Sanjar Bahodirovich Yusupov",
        "department": "Farmakologiya va klinik tillar kafedrasi",
        "degree": "t.f.d., professor",
        "bio": "Klinik farmakologiya va tibbiy rus tili o'qituvchisi. "
               "Retseptura bo'yicha darslik hammuallifi.",
        "phone": "+998 91 444 55 66",
    },
]


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------

def mask_db_url(url: str) -> str:
    """Parolni yashirgan holda baza manzilini qaytaradi."""
    if "@" not in url:
        return url
    scheme_sep = "://"
    if scheme_sep not in url:
        return url
    scheme, rest = url.split(scheme_sep, 1)
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        creds = f"{user}:***"
    return f"{scheme}{scheme_sep}{creds}@{host}"


async def get_or_create(session, stats, model, defaults=None, **keys):
    """Kalitlar bo'yicha topadi, bo'lmasa yaratadi. (obyekt, yaratildimi)."""
    found = (await session.execute(select(model).filter_by(**keys))).scalars().first()
    if found is not None:
        return found, False
    params = dict(keys)
    params.update(defaults or {})
    obj = model(**params)
    session.add(obj)
    await session.flush()
    stats[model.__tablename__] += 1
    return obj, True


async def has_rows(session, model, **keys) -> bool:
    """Berilgan shart bo'yicha yozuv bormi (bolalar to'plamini takrorlamaslik uchun)."""
    stmt = select(func.count()).select_from(model).filter_by(**keys)
    return bool((await session.execute(stmt)).scalar() or 0)


def add(session, stats, obj):
    session.add(obj)
    stats[obj.__tablename__] += 1
    return obj


def days_ago(n: int):
    return utcnow() - timedelta(days=n)


# ---------------------------------------------------------------------------
# Bosqichlar
# ---------------------------------------------------------------------------

async def seed_users(session, stats, tag, student_count):
    """Superadmin, xodimlar, guruhlar va talabalarni yaratadi."""
    accounts = []

    # Superadmin — mavjud bo'lsa yangisi yaratilmaydi.
    admin = (
        await session.execute(select(User).where(User.role == UserRole.superadmin))
    ).scalars().first()
    if admin is None:
        admin = add(session, stats, User(
            login=f"{tag}.admin",
            password_hash=hash_password(DEMO_PASSWORD),
            full_name="Demo Superadmin",
            role=UserRole.superadmin,
            is_active=True,
            must_change_password=False,
            phone_number="+998 71 200 00 00",
            department="Rektorat",
            degree="Administrator",
            preferred_language="uz",
            notification_prefs={"homework": True, "messages": True, "announcements": True},
            last_active=days_ago(0),
        ))
        await session.flush()
        accounts.append((admin.login, DEMO_PASSWORD, "superadmin", admin.full_name))
    else:
        print(f"  Superadmin mavjud — ishlatilmoqda: {admin.login} ({admin.full_name})")

    # Xodimlar
    employees = []
    for info in EMPLOYEES:
        login = f"{tag}.{info['suffix']}"
        emp, created = await get_or_create(
            session, stats, User, login=login,
            defaults=dict(
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=info["full_name"],
                role=UserRole.employee,
                is_active=True,
                must_change_password=False,
                phone_number=info["phone"],
                department=info["department"],
                degree=info["degree"],
                bio=info["bio"],
                preferred_language="uz",
                notification_prefs={"homework": True, "messages": True, "announcements": True},
                created_by_user_id=admin.id,
                last_active=days_ago(1),
            ),
        )
        employees.append(emp)
        if created:
            accounts.append((login, DEMO_PASSWORD, "employee", emp.full_name))

    # Guruhlar
    group_names = [f"{tag.upper()}-101", f"{tag.upper()}-102"]
    for name in group_names:
        await get_or_create(session, stats, StudentGroup, name=name)

    # Talabalar
    students = []
    for i in range(student_count):
        login = f"{tag}.talaba{i + 1}"
        name = STUDENT_NAMES[i % len(STUDENT_NAMES)]
        if i >= len(STUDENT_NAMES):
            name = f"{name} ({i + 1})"
        group = group_names[i % len(group_names)]
        student, created = await get_or_create(
            session, stats, User, login=login,
            defaults=dict(
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=name,
                username=f"@{login.replace('.', '_')}",
                role=UserRole.student,
                is_active=True,
                must_change_password=False,
                phone_number=f"+998 9{i % 10} {100 + i:03d} {10 + i:02d} {20 + i:02d}",
                student_group=group,
                parent_name=f"{name.split()[-1][:-2]}ov Otabek",
                parent_phone=f"+998 9{(i + 3) % 10} {200 + i:03d} 33 44",
                birth_date=f"{2004 - (i % 3)}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}",
                notes="Demo talaba — test ma'lumoti.",
                preferred_language="uz" if i % 3 else "ru",
                notification_prefs={
                    "homework": True,
                    "messages": True,
                    "announcements": i % 2 == 0,
                    "attendance": True,
                },
                target_topics=2 + (i % 3),
                target_quizzes=5,
                target_ai_questions=3,
                created_by_user_id=employees[i % len(employees)].id,
                last_active=days_ago(i % 5),
            ),
        )
        students.append(student)
        if created:
            accounts.append((login, DEMO_PASSWORD, "student", student.full_name))

    await session.flush()
    return admin, employees, group_names, students, accounts


async def seed_applications(session, stats, tag, employees, students):
    """Ro'yxatdan o'tish arizalari: tasdiqlangan, kutilayotgan va rad etilgan."""
    reviewer = employees[0]
    rows = [
        dict(
            login=f"{tag}.ariza1",
            full_name="Shahzod Normurodov",
            status=ApplicationStatus.approved,
            note="1-kurs, davolash fakulteti.",
            created_user_id=students[0].id if students else None,
            reviewed_by_user_id=reviewer.id,
            reviewed_at=days_ago(9),
            reject_reason=None,
        ),
        dict(
            login=f"{tag}.ariza2",
            full_name="Zilola Ismoilova",
            status=ApplicationStatus.pending,
            note="Pediatriya fakulteti, 2-kurs.",
            created_user_id=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
            reject_reason=None,
        ),
        dict(
            login=f"{tag}.ariza3",
            full_name="Otabek Sharipov",
            status=ApplicationStatus.rejected,
            note="Guruh raqami noaniq ko'rsatilgan.",
            created_user_id=None,
            reviewed_by_user_id=reviewer.id,
            reviewed_at=days_ago(4),
            reject_reason="Guruh raqami va pasport ma'lumotlari mos kelmadi.",
        ),
    ]
    for i, row in enumerate(rows):
        await get_or_create(
            session, stats, StudentApplication, login=row["login"],
            defaults=dict(
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=row["full_name"],
                username=f"@{row['login'].replace('.', '_')}",
                phone_number=f"+998 93 {700 + i:03d} 55 66",
                student_group=f"{tag.upper()}-101",
                parent_name="Normurodov Akmal",
                parent_phone="+998 93 555 11 22",
                birth_date="2005-03-15",
                note=row["note"],
                status=row["status"],
                reject_reason=row["reject_reason"],
                reviewed_by_user_id=row["reviewed_by_user_id"],
                created_user_id=row["created_user_id"],
                created_at=days_ago(10 - i),
                reviewed_at=row["reviewed_at"],
            ),
        )


async def seed_curriculum(session, stats, tag, employees):
    """Fanlar, fan materiallari, mavzular, mavzu materiallari va bilim bo'laklari."""
    label = f"({tag})"
    subjects = {}
    topics = []

    for s_index, s_info in enumerate(SUBJECTS):
        owner = employees[s_index % len(employees)]
        title = f"{s_info['title']} {label}"
        subject, _ = await get_or_create(
            session, stats, Subject, title=title,
            defaults=dict(description=s_info["description"], created_at=days_ago(60)),
        )
        subjects[s_info["title"]] = subject

        for m_type, m_title, m_detail, m_url in s_info["materials"]:
            await get_or_create(
                session, stats, SubjectMaterial,
                subject_id=subject.id, title=f"{m_title} {label}",
                defaults=dict(
                    material_type=m_type, detail=m_detail, url=m_url,
                    created_at=days_ago(45),
                ),
            )

        for t_index, t_info in enumerate(s_info["topics"]):
            topic, _ = await get_or_create(
                session, stats, Topic,
                subject_id=subject.id, title=f"{t_info['title']} {label}",
                defaults=dict(
                    employee_user_id=owner.id,
                    description=t_info["description"],
                    topic_type=t_info["topic_type"],
                    status=TopicStatus.active if t_index == 0 or s_index else TopicStatus.draft,
                    created_at=days_ago(40 - t_index),
                ),
            )
            topics.append((subject, topic, s_info))

            # Video material
            video, _ = await get_or_create(
                session, stats, TopicMaterial,
                topic_id=topic.id, material_type=MaterialType.video,
                title=f"{t_info['title']} - Video 1",
                defaults=dict(
                    uploaded_by_user_id=owner.id,
                    source_url=t_info["video_url"],
                    created_at=days_ago(38),
                ),
            )

            # Matnli materiallar + bilim bo'laklari (test generatsiyasi shularga tayanadi)
            for m_title, body in (("Leksika", t_info["leksika"]),
                                  ("Grammatika", t_info["grammatika"])):
                material, _ = await get_or_create(
                    session, stats, TopicMaterial,
                    topic_id=topic.id, material_type=MaterialType.text, title=m_title,
                    defaults=dict(
                        uploaded_by_user_id=owner.id,
                        raw_text=body,
                        processed_text=" ".join(body.split()),
                        created_at=days_ago(38),
                    ),
                )
                paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
                for c_index, paragraph in enumerate(paragraphs):
                    await get_or_create(
                        session, stats, KnowledgeChunk,
                        topic_id=topic.id, material_id=material.id, chunk_index=c_index,
                        defaults=dict(chunk_text=paragraph, created_at=days_ago(38)),
                    )

            # Transkript — video uchun (MaterialType.transcript ham to'lsin)
            await get_or_create(
                session, stats, TopicMaterial,
                topic_id=topic.id, material_type=MaterialType.transcript,
                title=f"{t_info['title']} - transkript",
                defaults=dict(
                    uploaded_by_user_id=owner.id,
                    source_url=video.source_url,
                    raw_text=(
                        "Assalomu alaykum, aziz talabalar. Bugungi ma'ruzamiz mavzusi — "
                        f"{t_info['title']}. Avval asosiy tushunchalarni ko'rib chiqamiz, "
                        "so'ngra klinik misollarga o'tamiz."
                    ),
                    created_at=days_ago(37),
                ),
            )

            # Hujjat material
            await get_or_create(
                session, stats, TopicMaterial,
                topic_id=topic.id, material_type=MaterialType.document,
                title=f"{t_info['title']} - taqdimot",
                defaults=dict(
                    uploaded_by_user_id=owner.id,
                    source_url=f"https://cdn.example.uz/demo/topic-{topic.id}.pdf",
                    created_at=days_ago(36),
                ),
            )

    return subjects, topics


async def seed_access_and_sessions(session, stats, topics, students):
    """Mavzuga ruxsat va talaba sessiyalari."""
    states = [SessionState.idle, SessionState.studying, SessionState.asking,
              SessionState.quiz_pending, SessionState.quiz_active, SessionState.quiz_done]
    for i, student in enumerate(students):
        assigned = topics[:4] if len(topics) >= 4 else topics
        for _, topic, _s in assigned:
            await get_or_create(
                session, stats, StudentTopicAccess,
                student_user_id=student.id, topic_id=topic.id,
                defaults=dict(
                    assigned_by_user_id=topic.employee_user_id,
                    assigned_at=days_ago(30),
                ),
            )
        current_topic = topics[i % len(topics)][1]
        await get_or_create(
            session, stats, StudentSession, student_user_id=student.id,
            defaults=dict(
                topic_id=current_topic.id,
                state=states[i % len(states)],
                question_count=i % 5,
                last_user_message="Ustoz, mitral klapan qayerda joylashgan?",
                started_at=days_ago(3),
            ),
        )


async def seed_quizzes(session, stats, topics, students):
    """Test urinishlari va savollari."""
    for i, student in enumerate(students):
        if await has_rows(session, QuizAttempt, student_user_id=student.id):
            continue
        for a_index in range(2):
            subject, topic, s_info = topics[(i + a_index) % len(topics)]
            bank = s_info["questions"][:5]
            finished = a_index == 0
            correct = rng.randint(2, 5) if finished else 0
            attempt = add(session, stats, QuizAttempt(
                student_user_id=student.id,
                topic_id=topic.id,
                employee_user_id=topic.employee_user_id,
                status=QuizAttemptStatus.finished if finished else QuizAttemptStatus.in_progress,
                language=student.preferred_language or "uz",
                total_questions=len(bank),
                correct_answers=correct,
                started_at=days_ago(6 - a_index),
                finished_at=days_ago(6 - a_index) if finished else None,
                report_sent_at=days_ago(6 - a_index) if finished else None,
            ))
            await session.flush()

            correct_left = correct
            for q_index, (text, options, answer, feedback) in enumerate(bank):
                if finished:
                    is_correct = correct_left > 0
                    correct_left -= 1 if is_correct else 0
                    student_answer = answer if is_correct else next(
                        k for k in options if k != answer
                    )
                    add(session, stats, QuizQuestion(
                        quiz_attempt_id=attempt.id,
                        question_order=q_index + 1,
                        question_text=text,
                        options=options,
                        expected_answer=answer,
                        student_answer=student_answer,
                        is_correct=is_correct,
                        feedback_text=feedback if is_correct else f"Noto'g'ri. {feedback}",
                        checked_at=days_ago(6 - a_index),
                    ))
                else:
                    add(session, stats, QuizQuestion(
                        quiz_attempt_id=attempt.id,
                        question_order=q_index + 1,
                        question_text=text,
                        options=options,
                        expected_answer=answer,
                    ))
            await session.flush()
            if not finished:
                sess = (
                    await session.execute(
                        select(StudentSession).where(
                            StudentSession.student_user_id == student.id
                        )
                    )
                ).scalars().first()
                if sess is not None:
                    sess.active_quiz_attempt_id = attempt.id


async def seed_exams(session, stats, subjects, topics, students):
    """Imtihon urinishlari va savollari (yakunlangan, davom etayotgan, muddati o'tgan)."""
    subject_list = list(subjects.values())
    for i, student in enumerate(students):
        if await has_rows(session, ExamAttempt, student_user_id=student.id):
            continue
        plan = [ExamStatus.finished, ExamStatus.in_progress]
        if i % 4 == 0:
            plan.append(ExamStatus.expired)
        for e_index, status in enumerate(plan):
            subject = subject_list[(i + e_index) % len(subject_list)]
            subject_topics = [t for s, t, _ in topics if s.id == subject.id]
            bank = []
            for s_data in SUBJECTS:
                if f"{s_data['title']} " in subject.title:
                    bank = s_data["questions"]
                    break
            bank = bank or SUBJECTS[0]["questions"]
            correct = rng.randint(3, len(bank)) if status == ExamStatus.finished else 0
            attempt = add(session, stats, ExamAttempt(
                student_user_id=student.id,
                subject_id=subject.id,
                title=f"{subject.title} — oraliq imtihon",
                topic_ids=[t.id for t in subject_topics],
                status=status,
                language=student.preferred_language or "uz",
                total_questions=len(bank),
                correct_answers=correct,
                duration_seconds=1800,
                started_at=days_ago(8 - e_index),
                finished_at=days_ago(8 - e_index) if status != ExamStatus.in_progress else None,
            ))
            await session.flush()

            correct_left = correct
            for q_index, (text, options, answer, feedback) in enumerate(bank):
                topic_id = subject_topics[q_index % len(subject_topics)].id if subject_topics else None
                answered = status == ExamStatus.finished or (
                    status == ExamStatus.in_progress and q_index < 2
                )
                is_correct = None
                student_answer = None
                if answered:
                    is_correct = correct_left > 0
                    correct_left -= 1 if is_correct else 0
                    student_answer = answer if is_correct else next(
                        k for k in options if k != answer
                    )
                add(session, stats, ExamQuestion(
                    exam_attempt_id=attempt.id,
                    topic_id=topic_id,
                    question_order=q_index + 1,
                    question_text=text,
                    options=options,
                    expected_answer=answer,
                    student_answer=student_answer,
                    is_correct=is_correct,
                    feedback_text=feedback if answered else None,
                    answered_at=days_ago(8 - e_index) if answered else None,
                ))
            await session.flush()


async def seed_homework(session, stats, tag, subjects, employees, students):
    """Uy vazifalari (umumiy va shaxsiy) hamda ularga javoblar."""
    label = f"({tag})"
    subject_list = list(subjects.values())
    homeworks = []
    for i, (title, text) in enumerate(HOMEWORKS):
        subject = subject_list[i % len(subject_list)]
        hw, _ = await get_or_create(
            session, stats, Homework, title=f"{title} {label}", student_user_id=None,
            defaults=dict(
                subject_id=subject.id,
                text=text,
                link="https://cdn.example.uz/demo/vazifa-namuna.pdf",
                created_by_user_id=employees[i % len(employees)].id,
                created_at=days_ago(12 - i),
            ),
        )
        homeworks.append(hw)

    # Shaxsiy vazifalar — birinchi ikki talabaga
    for i, student in enumerate(students[:2]):
        await get_or_create(
            session, stats, Homework,
            title=f"Shaxsiy topshiriq: qo'shimcha mashq {label}",
            student_user_id=student.id,
            defaults=dict(
                subject_id=subject_list[i % len(subject_list)].id,
                text="Oraliq nazoratdagi xatolar ustida ishlash uchun qo'shimcha "
                     "20 ta test topshiring va natijani yuboring.",
                created_by_user_id=employees[0].id,
                created_at=days_ago(5),
            ),
        )

    statuses = ["approved", "pending", "rejected"]
    for i, student in enumerate(students):
        for hw in homeworks[:2]:
            status = statuses[i % len(statuses)]
            graded = status != "pending"
            await get_or_create(
                session, stats, HomeworkSubmission,
                homework_id=hw.id, student_user_id=student.id,
                defaults=dict(
                    text="Vazifa bajarildi, rasm va izohlar biriktirildi.",
                    image_path=f"uploads/demo/hw-{hw.id}-{student.id}.jpg",
                    status=status,
                    grade={"approved": "5", "rejected": "2", "pending": None}[status],
                    teacher_feedback={
                        "approved": "Ajoyib ish, atamalar to'g'ri qo'llangan.",
                        "rejected": "Klapanlar noto'g'ri belgilangan, qayta ishlang.",
                        "pending": None,
                    }[status],
                    submitted_at=days_ago(4),
                    graded_at=days_ago(3) if graded else None,
                ),
            )


async def seed_schedule_and_attendance(session, stats, subjects, group_names,
                                       employees, students):
    """Dars jadvali va o'tgan 2 haftalik davomat yozuvlari."""
    subject_list = list(subjects.values())
    schedules = {}

    time_slots = [("09:00", "10:20"), ("10:30", "11:50"), ("13:00", "14:20"), ("14:30", "15:50")]
    for g_index, group in enumerate(group_names):
        group_schedules = []
        for s_index, subject in enumerate(subject_list):
            day = s_index + 1  # 1=Dushanba ... isoweekday bilan mos
            start, end = time_slots[(s_index + g_index) % len(time_slots)]
            sch, _ = await get_or_create(
                session, stats, LessonSchedule,
                student_group=group, day_of_week=day, subject_id=subject.id,
                start_time=start,
                defaults=dict(
                    end_time=end,
                    room=f"{chr(ord('A') + s_index)}-{201 + g_index * 10 + s_index}",
                    teacher_name=employees[s_index % len(employees)].full_name,
                    created_at=days_ago(50),
                ),
            )
            group_schedules.append(sch)
        schedules[group] = group_schedules

    today = date.today()
    marker = employees[0]
    reviewer = employees[1] if len(employees) > 1 else employees[0]
    excuse_cycle = [
        (ExcuseStatus.none, None),
        (ExcuseStatus.pending, "Kasal bo'lib qoldim, ma'lumotnoma tayyorlanmoqda."),
        (ExcuseStatus.approved, "Poliklinikadan ma'lumotnoma taqdim etildi."),
        (ExcuseStatus.rejected, "Transport muammosi, sabab asosli deb topilmadi."),
    ]

    for day_offset in range(13, -1, -1):
        lesson_date = today - timedelta(days=day_offset)
        iso_day = lesson_date.isoweekday()
        if iso_day > 5:
            continue  # dam olish kunlari dars yo'q
        for student in students:
            group = student.student_group
            for sch in schedules.get(group, []):
                if sch.day_of_week != iso_day:
                    continue
                roll = (student.id + day_offset + sch.id) % 10
                if roll < 6:
                    status = AttendanceStatus.present
                elif roll < 8:
                    status = AttendanceStatus.late
                elif roll < 9:
                    status = AttendanceStatus.excused
                else:
                    status = AttendanceStatus.absent

                if status == AttendanceStatus.excused:
                    exc_status, exc_reason = excuse_cycle[2]
                elif status == AttendanceStatus.absent:
                    exc_status, exc_reason = excuse_cycle[1 + (student.id + day_offset) % 3]
                else:
                    exc_status, exc_reason = excuse_cycle[0]

                reviewed = exc_status in (ExcuseStatus.approved, ExcuseStatus.rejected)
                await get_or_create(
                    session, stats, AttendanceRecord,
                    student_user_id=student.id, schedule_id=sch.id, lesson_date=lesson_date,
                    defaults=dict(
                        subject_id=sch.subject_id,
                        student_group=group,
                        status=status,
                        note={
                            AttendanceStatus.late: "10 daqiqa kechikdi.",
                            AttendanceStatus.absent: "Sababsiz qoldirdi.",
                            AttendanceStatus.excused: "Sababli qoldirildi.",
                        }.get(status),
                        marked_by_user_id=marker.id,
                        excuse_status=exc_status,
                        excuse_reason=exc_reason,
                        excuse_reviewed_by_user_id=reviewer.id if reviewed else None,
                        excuse_reviewed_at=days_ago(day_offset) if reviewed else None,
                        created_at=days_ago(day_offset),
                    ),
                )


async def seed_grades(session, stats, subjects, students):
    """Fanlar bo'yicha baholar."""
    def label_for(score: float) -> str:
        if score >= 86:
            return "A'lo"
        if score >= 71:
            return "Yaxshi"
        if score >= 56:
            return "Qoniqarli"
        return "Qoniqarsiz"

    for i, student in enumerate(students):
        for j, subject in enumerate(subjects.values()):
            score = float(55 + ((student.id * 7 + j * 13 + i) % 45))
            await get_or_create(
                session, stats, StudentGrade,
                student_user_id=student.id, subject_id=subject.id,
                defaults=dict(
                    score=score,
                    grade_label=label_for(score),
                    created_at=days_ago(7),
                ),
            )


async def seed_communication(session, stats, tag, employees, students, group_names,
                             topics, announcements, terms):
    """Chat, guruh chati, bildirishnomalar, saqlanganlar va murojaatlar."""
    for i, student in enumerate(students):
        employee = employees[i % len(employees)]

        # Shaxsiy chat
        if not await has_rows(session, ChatMessage, sender_id=student.id):
            add(session, stats, ChatMessage(
                sender_id=student.id, recipient_id=employee.id,
                message_text="Assalomu alaykum, ustoz! Ertangi amaliy mashg'ulotga "
                             "qaysi mavzuni tayyorlash kerak?",
                is_read=True, created_at=days_ago(2),
            ))
            add(session, stats, ChatMessage(
                sender_id=employee.id, recipient_id=student.id,
                message_text="Va alaykum assalom! Yurak anatomiyasi bo'yicha leksika "
                             "va klapanlar mavzusini takrorlab keling.",
                is_read=i % 2 == 0, created_at=days_ago(2),
            ))
            add(session, stats, ChatMessage(
                sender_id=student.id, recipient_id=employee.id,
                message_text="Rahmat, tushundim. Taqdimotni ham yuborsam bo'ladimi?",
                is_read=False, created_at=days_ago(1),
            ))

        # Bildirishnomalar
        if not await has_rows(session, NotificationLog, user_id=student.id):
            add(session, stats, NotificationLog(
                user_id=student.id, event_type="login",
                payload={"ip": "10.0.0.5", "device": "Android"},
                is_read=True, created_at=days_ago(1),
            ))
            add(session, stats, NotificationLog(
                user_id=student.id, event_type="homework_graded",
                payload={"homework": "Yurak kameralarini chizib, nomlang", "grade": "5"},
                is_read=False, created_at=days_ago(3),
            ))
            add(session, stats, NotificationLog(
                user_id=student.id, event_type="attendance_absent",
                payload={"subject": "Farmakologiya", "date": str(date.today() - timedelta(days=5))},
                is_read=False, created_at=days_ago(5),
            ))
            add(session, stats, NotificationLog(
                user_id=student.id, event_type="new_message",
                payload={"from": employee.full_name},
                is_read=False, created_at=days_ago(2),
            ))

        # Saqlanganlar
        _, topic, _s = topics[i % len(topics)]
        await get_or_create(
            session, stats, SavedItem,
            user_id=student.id, item_type=SavedItemType.topic, item_id=topic.id,
            defaults=dict(title=topic.title[:255], subtitle="Mavzu", created_at=days_ago(6)),
        )
        term = terms[i % len(terms)]
        await get_or_create(
            session, stats, SavedItem,
            user_id=student.id, item_type=SavedItemType.term, item_id=term.id,
            defaults=dict(title=term.word, subtitle=term.translation, created_at=days_ago(5)),
        )
        ann = announcements[i % len(announcements)]
        await get_or_create(
            session, stats, SavedItem,
            user_id=student.id, item_type=SavedItemType.announcement, item_id=ann.id,
            defaults=dict(title=ann.title[:255], subtitle=ann.announcement_type,
                          created_at=days_ago(4)),
        )

        # Klinik arena
        if not await has_rows(session, ClinicalArenaAttempt, student_user_id=student.id):
            score = rng.randint(40, 100)
            add(session, stats, ClinicalArenaAttempt(
                student_user_id=student.id, mode="case", status="finished",
                scenario_or_opponent=CASE_SCENARIOS[i % len(CASE_SCENARIOS)],
                score=score, is_winner=score == 100,
                points_awarded=score * 3 // 2,
                created_at=days_ago(3), finished_at=days_ago(3),
            ))
            duel_score = rng.randint(0, 5)
            add(session, stats, ClinicalArenaAttempt(
                student_user_id=student.id, mode="duel", status="finished",
                scenario_or_opponent=DUEL_OPPONENTS[i % len(DUEL_OPPONENTS)],
                issued_payload={
                    "question_indexes": [0, 3, 5, 7, 9],
                    "opponent": {"name": DUEL_OPPONENTS[i % len(DUEL_OPPONENTS)],
                                 "level": 2 + i % 3},
                },
                score=duel_score, is_winner=duel_score >= 3,
                points_awarded=duel_score * 20,
                created_at=days_ago(2), finished_at=days_ago(2),
            ))
            add(session, stats, ClinicalArenaAttempt(
                student_user_id=student.id, mode="duel", status="issued",
                scenario_or_opponent=DUEL_OPPONENTS[(i + 1) % len(DUEL_OPPONENTS)],
                issued_payload={"question_indexes": [1, 2, 4, 6, 8]},
                score=0, is_winner=False, points_awarded=0,
                created_at=days_ago(0),
            ))

    # Guruh chati
    for g_index, group in enumerate(group_names):
        if await has_rows(session, GroupChatMessage, group_name=group):
            continue
        members = [s for s in students if s.student_group == group]
        if not members:
            continue
        employee = employees[g_index % len(employees)]
        add(session, stats, GroupChatMessage(
            group_name=group, sender_id=employee.id,
            message_text=f"Salom, {group}! Ertangi amaliyot 09:00 da A-201 xonasida "
                         "bo'ladi. Xalatni unutmang.",
            created_at=days_ago(2),
        ))
        for m_index, member in enumerate(members[:3]):
            add(session, stats, GroupChatMessage(
                group_name=group, sender_id=member.id,
                message_text=[
                    "Rahmat, ustoz! Tushundik.",
                    "Ustoz, taqdimot fayli qayerda joylashgan?",
                    "Men kutubxonadan qo'shimcha adabiyot olib keldim, kerak bo'lsa ulashaman.",
                ][m_index],
                created_at=days_ago(1),
            ))
        add(session, stats, GroupChatMessage(
            group_name=group, sender_id=employee.id,
            message_text="Taqdimot «Materiallar» bo'limida, fan sahifasida turibdi.",
            image_path=f"uploads/demo/{group.lower()}-jadval.png",
            created_at=days_ago(1),
        ))

    # Murojaatlar
    for i, (req_type, subject_text, message, status, response) in enumerate(REQUESTS):
        student = students[i % len(students)]
        answered = status in (RequestStatus.resolved, RequestStatus.rejected)
        await get_or_create(
            session, stats, StudentRequest,
            student_user_id=student.id, subject=f"{subject_text} ({tag})",
            defaults=dict(
                request_type=req_type,
                message=message,
                status=status,
                response=response,
                responded_by_user_id=employees[i % len(employees)].id if answered else None,
                created_at=days_ago(8 - i),
            ),
        )


async def seed_reference(session, stats, tag):
    """E'lonlar, lug'at va yordam bo'limi (FAQ)."""
    announcements = []
    for i, (title, a_type, content) in enumerate(ANNOUNCEMENTS):
        ann, _ = await get_or_create(
            session, stats, Announcement, title=f"{title} ({tag})",
            defaults=dict(
                content=content,
                announcement_type=a_type,
                views=rng.randint(15, 400),
                created_at=days_ago(14 - i * 2),
            ),
        )
        announcements.append(ann)

    terms = []
    for row in TERMS:
        word, transcription, gender, translation, category, desc, ex_ru, ex_uz = row
        term, _ = await get_or_create(
            session, stats, MedicalTerm, word=word,
            defaults=dict(
                transcription=transcription, gender=gender, translation=translation,
                category=category, description=desc, example_ru=ex_ru, example_uz=ex_uz,
                created_at=days_ago(20),
            ),
        )
        terms.append(term)

    for category, question, answer, order in FAQS:
        await get_or_create(
            session, stats, FaqEntry, question=question,
            defaults=dict(
                category=category, answer=answer, sort_order=order,
                is_active=True, created_at=days_ago(25),
            ),
        )

    return announcements, terms


# ---------------------------------------------------------------------------
# Asosiy oqim
# ---------------------------------------------------------------------------

async def run(student_count: int, tag: str) -> None:
    stats = Counter()
    async with AsyncSessionLocal() as session:
        print("\n[1/8] Foydalanuvchilar va guruhlar...")
        admin, employees, group_names, students, accounts = await seed_users(
            session, stats, tag, student_count
        )

        print("[2/8] Ro'yxatdan o'tish arizalari...")
        await seed_applications(session, stats, tag, employees, students)

        print("[3/8] Fanlar, mavzular va materiallar...")
        subjects, topics = await seed_curriculum(session, stats, tag, employees)

        print("[4/8] Ma'lumotnoma: e'lonlar, lug'at, FAQ...")
        announcements, terms = await seed_reference(session, stats, tag)

        print("[5/8] Mavzuga ruxsat va sessiyalar...")
        await seed_access_and_sessions(session, stats, topics, students)

        print("[6/8] Testlar va imtihonlar...")
        await seed_quizzes(session, stats, topics, students)
        await seed_exams(session, stats, subjects, topics, students)

        print("[7/8] Uy vazifalari, jadval, davomat va baholar...")
        await seed_homework(session, stats, tag, subjects, employees, students)
        await seed_schedule_and_attendance(
            session, stats, subjects, group_names, employees, students
        )
        await seed_grades(session, stats, subjects, students)

        print("[8/8] Chat, bildirishnoma, saqlanganlar, murojaatlar...")
        await seed_communication(
            session, stats, tag, employees, students, group_names,
            topics, announcements, terms
        )

        await session.commit()

    print_report(stats, accounts, admin, tag)


def print_report(stats: Counter, accounts, admin, tag: str) -> None:
    print("\n" + "=" * 62)
    print("QO'SHILGAN YOZUVLAR")
    print("=" * 62)
    if not stats:
        print("  Yangi yozuv qo'shilmadi — demo to'plam allaqachon mavjud.")
    else:
        for table in sorted(stats):
            print(f"  {table:<28} {stats[table]:>6}")
        print(f"  {'JAMI':<28} {sum(stats.values()):>6}")

    print("\n" + "=" * 62)
    print("DEMO HISOBLAR")
    print("=" * 62)
    if accounts:
        print(f"  {'LOGIN':<24} {'PAROL':<12} {'ROL':<11} ISM")
        print("  " + "-" * 58)
        for login, password, role, name in accounts:
            print(f"  {login:<24} {password:<12} {role:<11} {name}")
    else:
        print("  Yangi hisob yaratilmadi (barchasi mavjud edi).")
        print(f"  Mavjud loginlar: {tag}.ustoz1, {tag}.ustoz2, {tag}.talaba1 ...")
        print(f"  Parol: {DEMO_PASSWORD}")
    if admin is not None and admin.login and not any(a[0] == admin.login for a in accounts):
        print(f"\n  Superadmin (mavjud, paroli o'zgartirilmadi): {admin.login}")
    print()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bazani demo ma'lumot bilan to'ldiradi (hech narsa o'chirilmaydi)."
    )
    parser.add_argument("--students", type=int, default=8,
                        help="Yaratiladigan talabalar soni (default: 8)")
    parser.add_argument("--suffix", default="",
                        help="Mustaqil yangi to'plam uchun qo'shimcha belgi, masalan: 2")
    parser.add_argument("--yes", action="store_true",
                        help="Tasdiq so'ramasdan ishga tushirish")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.students < 1:
        print("Xatolik: --students kamida 1 bo'lishi kerak.")
        return 1
    suffix = args.suffix.strip().replace(" ", "")
    tag = f"demo{suffix}" if suffix else "demo"

    print("=" * 62)
    print("DEMO MA'LUMOT YUKLASH")
    print("=" * 62)
    print(f"  Baza      : {mask_db_url(config.DATABASE_URL)}")
    print(f"  To'plam   : {tag}")
    print(f"  Talabalar : {args.students}")
    print("  Rejim     : faqat QO'SHISH (mavjud ma'lumot o'chirilmaydi)")

    if not args.yes:
        answer = input("\n  Yuqoridagi bazaga demo ma'lumot yozilsinmi? [ha/yo'q]: ")
        if answer.strip().lower() not in {"ha", "yes", "y", "ha'", "xa"}:
            print("  Bekor qilindi.")
            return 1

    asyncio.run(run(args.students, tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
