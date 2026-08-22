# -*- coding: utf-8 -*-
"""
نظام الأدوار المتقدم.

كل دور هنا كائن بيانات كامل: اسم، وصف، قصة شخصية، هدف علني، هدف سري،
قالب سر شخصي، قدرة خاصة (بنوعها التقني الذي يفهمه محرك القدرات في
abilities.py)، عدد استخدامات، نقطة ضعف، معلومة أولية، علاقات محتملة،
ومهمة جانبية.

هذه الوحدة لا تتعامل مع تيليجرام ولا قاعدة البيانات مباشرة؛ فقط تعريف
البيانات ومنطق الاختيار والتوازن، بحيث يسهل توسعتها لاحقًا (أدوار جديدة
= عنصر جديد في ROLES، بلا تعديل أي مكان آخر عادةً).

`tier` يُستخدم فقط لتحقيق التوازن أثناء الاختيار:
- "core"        : أدوار تحقيق/دعم أساسية، آمنة لأي عدد لاعبين.
- "support"     : أدوار مساندة أقل قوة.
- "social"      : أدوار اجتماعية/معلوماتية خفيفة.
- "chaotic"     : أدوار تصنع فوضى أو خداعًا (خائن، كذاب، صانع فوضى...).
  تُحدَّد بعدد أقصى صغير حتى لا تطغى على اللعبة.
- "narrative"   : أدوار سردية غالبًا سلبية (بلا قدرة فعّالة)، تضيف عمقًا
  للقصة والأسرار دون التأثير الميكانيكي المباشر.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import random

import db


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    emoji: str
    description: str
    backstory: str
    public_goal: str
    secret_goal: str
    secret_template: str
    ability_name: str
    ability_description: str
    ability_type: str          # يُستخدم في abilities.py لتحديد التنفيذ
    ability_uses: int
    needs_target: bool
    weakness: str
    initial_info: str
    possible_relations: List[str]
    side_quest: str
    tier: str


ROLES: List[Role] = [
    Role(
        id="detective", name="المحقق", emoji="🕵️",
        description="عقل تحليلي يبحث عن الحقيقة عبر الأدلة لا الانطباعات.",
        backstory="عمل سابقًا في قضايا غامضة لم تُحل، وهذه القضية تذكّره بواحدة منها.",
        public_goal="كشف الحقيقة الكاملة قبل ختام القصة.",
        secret_goal="إثبات كفاءته بحل القضية دون مساعدة أحد بشكل ظاهر.",
        secret_template="تعرف أن أحد الحاضرين قال كذبة صغيرة منذ بداية اللقاء، دون أن تعرف لماذا كذب بالتحديد.",
        ability_name="تحقيق في دليل",
        ability_description="يفحص دليلًا متداولًا بعمق ويكشف تفصيلًا إضافيًا فيه.",
        ability_type="investigate_evidence", ability_uses=2, needs_target=False,
        weakness="إذا انكشف دورك للجميع، ستصبح هدفًا مباشرًا للتضليل والاتهام.",
        initial_info="تعرف أن القضية أعقد مما تبدو عليه ظاهريًا.",
        possible_relations=["witness", "false_accuser", "shadow"],
        side_quest="اكتشف تناقضًا واحدًا صريحًا في أقوال أحدهم قبل نهاية اللعبة.",
        tier="core",
    ),
    Role(
        id="witness", name="الشاهد", emoji="👁️",
        description="رأى شيئًا في البداية لم يستطع تفسيره وقتها.",
        backstory="كان حاضرًا في مكان غير متوقع لحظة بدء الأحداث.",
        public_goal="مساعدة المجموعة على فهم ما حدث فعلًا في البداية.",
        secret_goal="حماية نفسك من اتهام مباشر بسبب مكانك في تلك اللحظة.",
        secret_template="رأيت شخصًا يغادر المكان بسرعة في اللحظة الحرجة، لكنك لست متأكدًا من هويته بالكامل.",
        ability_name="كشف تلميح",
        ability_description="يكشف تلميحًا غامضًا عن حدث ماضٍ مرتبط بالقصة.",
        ability_type="reveal_hint", ability_uses=1, needs_target=False,
        weakness="شهادتك وحدها غير كافية، وقد يُشكَّك في دقتها بسهولة.",
        initial_info="تحمل ذكرى بصرية واحدة قد تكون مفتاحًا مهمًا لاحقًا.",
        possible_relations=["detective", "liar"],
        side_quest="شارك تلميحًا واحدًا على الأقل يغيّر اتجاه النقاش.",
        tier="core",
    ),
    Role(
        id="guardian", name="الحارس", emoji="🛡️",
        description="يميل لحماية من يثق بهم أكثر من كشف الحقيقة.",
        backstory="فقد شخصًا مقربًا في ظرف مشابه، ولا يريد تكرار ذلك.",
        public_goal="إبقاء أكبر عدد ممكن من اللاعبين بأمان حتى النهاية.",
        secret_goal="حماية شخص محدد تشعر أنه الأضعف في المجموعة.",
        secret_template="قطعت على نفسك وعدًا صامتًا بحماية أحد الحاضرين مهما كلّف الأمر.",
        ability_name="حماية لاعب",
        ability_description="يحمي لاعبًا مستهدفًا من أثر حدث سلبي في هذه الجولة.",
        ability_type="protect", ability_uses=2, needs_target=True,
        weakness="لا يمكنك حماية نفسك بقدرتك الخاصة.",
        initial_info="تشعر أن أحدهم بحاجة لحماية أكثر من غيره.",
        possible_relations=["heir", "survivor"],
        side_quest="احمِ نفس الشخص مرتين متتاليتين دون أن يعرف أحد بذلك.",
        tier="core",
    ),
    Role(
        id="stranger", name="الغريب", emoji="👤",
        description="لا أحد يعرفه جيدًا، وهذا بالضبط ما يمنحه مساحة للمناورة.",
        backstory="وصل إلى هذه المجموعة بالصدفة، أو هكذا يقول.",
        public_goal="الاندماج وكسب ثقة المجموعة دون إثارة الشبهات.",
        secret_goal="إخفاء سبب وجودك الحقيقي هنا أطول فترة ممكنة.",
        secret_template="لديك سبب شخصي غير معلن جعلك تقبل الحضور إلى هذا المكان بالذات.",
        ability_name="اندماج هادئ",
        ability_description="يقلّل بشكل طفيف احتمال أن يوجَّه إليه الشك في الجولة الحالية (تأثير سردي).",
        ability_type="passive", ability_uses=0, needs_target=False,
        weakness="أي دليل واحد يربطك بالمكان قبل الحادثة قد يقلب الرأي العام ضدك بسرعة.",
        initial_info="لا تملك معلومات مسبقة عن أي من الحاضرين.",
        possible_relations=["spy", "impostor"],
        side_quest="تجنّب أن يُطلب استجوابك حتى الجولة الأخيرة.",
        tier="narrative",
    ),
    Role(
        id="mediator", name="الوسيط", emoji="🤝",
        description="يفضّل نقل الكلام بهدوء بدل المواجهة المباشرة.",
        backstory="عُرف دائمًا بقدرته على تهدئة الخلافات بين الناس.",
        public_goal="الحفاظ على تماسك المجموعة وتقليل الصدام المباشر.",
        secret_goal="استخدام موقعك المحايد لتمرير معلومة تخدم طرفًا تثق به.",
        secret_template="تعرف معلومة صغيرة يفضّل صاحبها ألا تُقال بصوت عالٍ أمام الجميع.",
        ability_name="نقل سرّي",
        ability_description="ينقل ملاحظة أو معلومة صغيرة إلى لاعب آخر في الخاص دون علم البقية.",
        ability_type="spy_info", ability_uses=2, needs_target=True,
        weakness="إذا اكتُشف أنك تنقل معلومات سرًا، ستفقد ثقة الطرفين دفعة واحدة.",
        initial_info="تعرف من الأقرب لمن منذ البداية بشكل تقريبي.",
        possible_relations=["secret_partner", "judge"],
        side_quest="مرّر معلومة واحدة على الأقل غيّرت قرار شخص ما.",
        tier="support",
    ),
    Role(
        id="researcher", name="الباحث", emoji="📚",
        description="يحب مقارنة التفاصيل الصغيرة قبل إصدار أي حكم.",
        backstory="معتاد على العمل بصبر مع معلومات ناقصة أو متضاربة.",
        public_goal="بناء صورة متماسكة من الأدلة المتفرقة.",
        secret_goal="إثبات نظرية شخصية توصلت إليها منذ الجولة الأولى.",
        secret_template="لديك نظرية مبكرة عمّا يجري، لم تشاركها بعد لأنها تبدو غير معقولة.",
        ability_name="مقارنة أدلة",
        ability_description="يقارن بين قطعتي دليل متاحتين ويكشف نقطة اتفاق أو تناقض بينهما.",
        ability_type="analyze_evidence", ability_uses=2, needs_target=False,
        weakness="نظرياتك المبكرة قد تكون خاطئة تمامًا وتُضعف مصداقيتك إن أُعلنت بتسرّع.",
        initial_info="تلاحظ التفاصيل الصغيرة أكثر من غيرك.",
        possible_relations=["expert", "historian"],
        side_quest="اربط بين دليلين لم يربط بينهما أحد من قبل.",
        tier="core",
    ),
    Role(
        id="shadow", name="الظل", emoji="🌑",
        description="يراقب من بعيد، ونادرًا ما يتحدث أولًا.",
        backstory="اعتاد أن يكون آخر من يُشتبه به لأنه آخر من يتكلم.",
        public_goal="جمع أكبر قدر من المعلومات دون لفت الانتباه.",
        secret_goal="البقاء غير مكتشَف الدور حتى الجولة الأخيرة.",
        secret_template="تراقب شخصًا معينًا بعناية منذ البداية، لسبب لم تُفصح عنه بعد.",
        ability_name="مراقبة صامتة",
        ability_description="يراقب لاعبًا مستهدفًا ويحصل على ملاحظة عن سلوكه دون أن يشعر المستهدَف.",
        ability_type="spy_info", ability_uses=3, needs_target=True,
        weakness="كل مراقبة إضافية تزيد فرصة أن يلاحظ أحدهم أنك تتابعه بصمت.",
        initial_info="لا أحد يتوقع أنك تراقب بهذا القدر من الدقة.",
        possible_relations=["spy", "informal_detective"],
        side_quest="راقب نفس الشخص ثلاث مرات دون أن يُكتشف أمرك.",
        tier="support",
    ),
    Role(
        id="silent_narrator", name="الراوي الصامت", emoji="🤫",
        description="يعرف تفاصيل من القصة أكثر مما يكشفه عادةً.",
        backstory="مرتبط بطريقة ما بجذور هذه القصة قبل أن تبدأ أحداثها.",
        public_goal="مشاهدة الأحداث تتكشف كما يجب أن تتكشف.",
        secret_goal="عدم التدخل المباشر إلا في اللحظة الحاسمة فقط.",
        secret_template="تعرف تفصيلًا من خلفية هذه القصة لا يعرفه أحد آخر في المجموعة.",
        ability_name="لمحة خلفية",
        ability_description="يحصل على سطر إضافي من خلفية القصة كل بضع جولات (تأثير سردي بلا استهلاك يدوي).",
        ability_type="passive", ability_uses=0, needs_target=False,
        weakness="معرفتك العميقة تجعلك مثيرًا للشك إن ظهرت بتفصيل دقيق جدًا في وقت مبكر.",
        initial_info="تعرف خلفية أعمق من خلفية بقية الحاضرين عن هذا المكان.",
        possible_relations=["secret_holder", "historian"],
        side_quest="لا تكشف أكثر من تفصيل خلفية واحد طوال اللعبة.",
        tier="narrative",
    ),
    Role(
        id="keyholder", name="حامل المفتاح", emoji="🗝️",
        description="يحمل وسيلة الوصول إلى ما هو مخفي عن البقية.",
        backstory="أُعطي هذا المفتاح (حرفيًا أو رمزيًا) دون أن يفهم سببه الكامل.",
        public_goal="استخدام ما يملكه في اللحظة المناسبة لخدمة الحقيقة.",
        secret_goal="تحديد من يستحق معرفة ما وراء ما تملك مفتاحه.",
        secret_template="تحمل وسيلة للوصول إلى شيء مغلق، لكنك لا تعرف بعد ما بداخله بالضبط.",
        ability_name="فتح دليل مقفل",
        ability_description="يكشف دليلًا سريًا إضافيًا لا يعرفه بقية اللاعبين.",
        ability_type="unlock_secret_evidence", ability_uses=1, needs_target=False,
        weakness="بمجرد استخدام قدرتك، يصبح من الواضح أنك كنت تملك شيئًا مميزًا.",
        initial_info="تعرف أن هناك شيئًا مخفيًا في هذا المكان تحديدًا.",
        possible_relations=["heir", "keeper_of_secrets"],
        side_quest="استخدم ما تملكه في التوقيت الذي يصنع أكبر فرق.",
        tier="core",
    ),
    Role(
        id="observer", name="المراقب", emoji="👁️",
        description="ينتبه لمن يتحدث كثيرًا ومن يصمت أكثر مما ينبغي.",
        backstory="عادة ما يلاحظ أنماط الكلام قبل أن يلاحظ الكلام نفسه.",
        public_goal="تقديم ملاحظات محايدة عن مسار النقاش للمجموعة.",
        secret_goal="استخدام هذه الملاحظات لصالح استنتاج شخصي لم يعلنه بعد.",
        secret_template="لاحظت نمطًا غريبًا في كلام أحدهم منذ الجولة الأولى.",
        ability_name="تقرير النشاط",
        ability_description="يطلب تقريرًا بسيطًا عن الأكثر والأقل مشاركة في نقاش الجولة الحالية.",
        ability_type="stats_report", ability_uses=3, needs_target=False,
        weakness="ملاحظاتك مجرد إحصاء ظاهري، وقد تكون مضللة تمامًا كدليل.",
        initial_info="تعرف كيف تُقرأ أنماط الكلام الجماعي بسرعة.",
        possible_relations=["detective", "expert"],
        side_quest="استخدم ملاحظة نشاط واحدة على الأقل لتوجيه النقاش.",
        tier="support",
    ),
    Role(
        id="heir", name="الوريث", emoji="👑",
        description="له علاقة مباشرة بما هو على المحك في هذه القصة.",
        backstory="ما يحدث هنا يمسّ إرثًا أو مكانة يخصه شخصيًا.",
        public_goal="حماية ما تبقى مما تركه من سبقه.",
        secret_goal="إخفاء مدى استفادتك الشخصية من نتيجة هذه القضية.",
        secret_template="نتيجة هذه القضية ستفيدك شخصيًا بطريقة لم تخبر بها أحدًا.",
        ability_name="حماية إرث",
        ability_description="يحمي سرًا أو دليلًا محددًا من أن يُكشف هذه الجولة.",
        ability_type="protect", ability_uses=1, needs_target=False,
        weakness="أي شك حول مصلحتك الشخصية سيُنظر إليه بجدية مضاعفة.",
        initial_info="تعرف أن نتيجة هذه القصة تمسّك مباشرة.",
        possible_relations=["keyholder", "traitor"],
        side_quest="حافظ على عدم كشف مصلحتك الشخصية حتى الجولة الأخيرة.",
        tier="core",
    ),
    Role(
        id="survivor", name="الناجي", emoji="🩸",
        description="مرّ بحادثة مشابهة من قبل ونجا منها بصعوبة.",
        backstory="ما زال يحمل أثر تلك التجربة، وإن لم يظهره كثيرًا.",
        public_goal="الخروج من هذه القصة دون تكرار خطأ الماضي.",
        secret_goal="عدم الوقوع في نفس الموقف الذي كاد يكلفك كل شيء سابقًا.",
        secret_template="نجوت من موقف شبيه بهذا من قبل، وما زلت تحمل أثره دون أن تخبر أحدًا.",
        ability_name="مقاومة الصدمة",
        ability_description="يتجاوز أثر حدث سلبي واحد يستهدفه مباشرة (تأثير سردي تلقائي مرة واحدة).",
        ability_type="passive", ability_uses=0, needs_target=False,
        weakness="ذكرياتك تجعلك سريع الحكم أحيانًا بناءً على تجربتك الماضية لا الحاضر.",
        initial_info="تشعر بتشابه غريب بين هذه القصة وتجربة سابقة مررت بها.",
        possible_relations=["guardian", "victim_role"],
        side_quest="ساعد شخصًا آخر على تجنّب الخطأ الذي وقعت فيه أنت سابقًا.",
        tier="narrative",
    ),
    Role(
        id="secret_holder", name="صاحب السر", emoji="📜",
        description="يحمل معلومة أكبر من حجم دوره الظاهري.",
        backstory="عرف شيئًا لم يكن يُفترض أن يعرفه بهذه السهولة.",
        public_goal="عدم لفت الانتباه إلى حجم ما تعرفه فعلًا.",
        secret_goal="اختيار اللحظة المناسبة (أو عدم الاختيار أبدًا) للكشف عمّا تعرفه.",
        secret_template="تعرف تفصيلًا محوريًا في هذه القصة، لكنه ثقيل بما يكفي لتفضّل حمله وحدك قدر الإمكان.",
        ability_name="كشف جزئي",
        ability_description="يكشف جزءًا محدودًا من سرّه الكبير دون الكشف عنه بالكامل.",
        ability_type="reveal_hint", ability_uses=1, needs_target=False,
        weakness="إن كُشف سرّك بالكامل دفعة واحدة، ستفقد أي قيمة تفاوضية كانت لديك.",
        initial_info="تحمل معلومة واحدة يمكن أن تغيّر مسار القصة كاملة.",
        possible_relations=["keyholder", "judge"],
        side_quest="حافظ على سرك الكبير حتى الجولة قبل الأخيرة على الأقل.",
        tier="core",
    ),
    Role(
        id="informal_detective", name="المحقق غير الرسمي", emoji="🔎",
        description="يحقق بطريقته الخاصة، بعيدًا عن أي صفة رسمية.",
        backstory="لطالما شعر أن له حسًّا للتحقيق لم يُتح له استخدامه رسميًا من قبل.",
        public_goal="إثبات أن حدسه يستحق الثقة رغم غياب أي صفة رسمية.",
        secret_goal="التفوق على أي محقق رسمي حاضر في كشف الحقيقة أولًا.",
        secret_template="تشك في شخص معين منذ البداية دون أي دليل ملموس بعد.",
        ability_name="سؤال إضافي",
        ability_description="يطرح سؤال استجواب إضافيًا على المجموعة هذه الجولة.",
        ability_type="extra_question", ability_uses=2, needs_target=False,
        weakness="بلا صفة رسمية، قد لا يأخذ أحد استنتاجاتك على محمل الجد بسهولة.",
        initial_info="لديك حدس مبكر تجاه شخص واحد في المجموعة.",
        possible_relations=["detective", "false_accuser"],
        side_quest="اطرح سؤالًا واحدًا يكشف تناقضًا فعليًا.",
        tier="support",
    ),
    Role(
        id="neutral_voice", name="الصوت المحايد", emoji="⚖️",
        description="يرفض الانحياز المبكر لأي طرف قبل رؤية الصورة كاملة.",
        backstory="عانى سابقًا من أثر حكم متسرّع أصدره أو صدر بحقه.",
        public_goal="إبقاء النقاش عادلًا ومتوازنًا قدر الإمكان.",
        secret_goal="منع تكرار خطأ إصدار حكم ظالم كما حدث في تجربتك الماضية.",
        secret_template="أُصدر بحقك حكم غير عادل مرة في الماضي، وهذا يشكّل كل قراراتك هنا.",
        ability_name="تحييد اتهام",
        ability_description="يخفف أثر اتهام غير مدعوم بدليل كافٍ في هذه الجولة.",
        ability_type="neutralize_note", ability_uses=1, needs_target=False,
        weakness="حيادك الزائد قد يُفسَّر أحيانًا على أنه تستّر أو عدم اكتراث.",
        initial_info="تدرك جيدًا كيف يبدو الحكم المتسرع من الداخل.",
        possible_relations=["judge", "witness"],
        side_quest="امنع اتهامًا واحدًا ظالمًا من التأثير على النقاش.",
        tier="support",
    ),
    Role(
        id="medic", name="الطبيب", emoji="🩺",
        description="يهتم بمن حوله عمليًا أكثر من اهتمامه بالنقاش نفسه.",
        backstory="اعتاد أن يكون أول من يتحرك عند أي أزمة.",
        public_goal="الحفاظ على سلامة المجموعة قدر استطاعته.",
        secret_goal="عدم تكرار موقف عجزت فيه سابقًا عن حماية أحدهم.",
        secret_template="فشلت مرة في حماية شخص كنت مسؤولًا عنه، وما زلت تحمل هذا الشعور.",
        ability_name="عناية سريعة",
        ability_description="يحمي لاعبًا مستهدفًا من أثر سلبي في هذه الجولة، بأسلوب عملي لا تحقيقي.",
        ability_type="protect", ability_uses=2, needs_target=True,
        weakness="تركيزك على الحماية العملية قد يجعلك تفوّت تفاصيل تحقيقية مهمة.",
        initial_info="تلاحظ أول من يتأثر فعليًا بأي حدث في المجموعة.",
        possible_relations=["guardian", "survivor"],
        side_quest="احمِ لاعبًا مختلفًا في كل مرة تستخدم فيها قدرتك.",
        tier="core",
    ),
    Role(
        id="traitor", name="الخائن", emoji="🎭",
        description="يبدو متعاونًا، لكن ولاءه الحقيقي في مكان آخر.",
        backstory="التزم بشيء أو شخص خارج هذه المجموعة قبل أن تبدأ القصة.",
        public_goal="الظهور بمظهر المتعاون الكامل مع المجموعة.",
        secret_goal="خدمة جهة أو شخص غائب عن هذا النقاش دون أن يُكتشف أمرك.",
        secret_template="التزمت بشيء أو شخص خارج هذه المجموعة قبل بدء الأحداث، وهذا يوجّه قراراتك سرًا.",
        ability_name="تضليل دليل",
        ability_description="يجعل قطعة دليل متداولة تبدو أقل موثوقية مما هي عليه فعلًا.",
        ability_type="propagate_rumor", ability_uses=2, needs_target=False,
        weakness="إن انكشف ولاؤك الحقيقي، ستفقد ثقة الجميع دفعة واحدة وبلا رجعة.",
        initial_info="تعرف بالضبط لمصلحة من يجب أن تعمل، ولو بصمت.",
        possible_relations=["heir", "impostor"],
        side_quest="حافظ على ولائك الحقيقي مخفيًا حتى الجولة الأخيرة.",
        tier="chaotic",
    ),
    Role(
        id="genius", name="العبقري", emoji="🧠",
        description="يربط التفاصيل بسرعة تفوق البقية أحيانًا.",
        backstory="اعتاد الناس أن يطلبوا رأيه في المواقف المعقدة.",
        public_goal="تقديم تحليل يساعد المجموعة على التفكير بوضوح أكبر.",
        secret_goal="إثبات تفوقك التحليلي حتى لو على حساب تعاون الفريق أحيانًا.",
        secret_template="توصلت لاستنتاج مبكر تخشى أنه صحيح جدًا لدرجة مقلقة.",
        ability_name="تحليل دقيق",
        ability_description="يحصل على تحليل إضافي أعمق لقطعة دليل أو موقف حالي.",
        ability_type="analyze_evidence", ability_uses=2, needs_target=False,
        weakness="ثقتك الزائدة بتحليلك قد تجعلك تتجاهل تفصيلًا بسيطًا لكنه حاسم.",
        initial_info="ترى نمطًا لم يلاحظه أحد بعد في تسلسل الأحداث.",
        possible_relations=["researcher", "expert"],
        side_quest="قدّم استنتاجًا واحدًا لاحقًا تبيّن أنه دقيق تمامًا.",
        tier="support",
    ),
    Role(
        id="spy", name="المتجسس", emoji="🕵️",
        description="يجمع المعلومات بهدوء لحساب جهة لا يعلنها.",
        backstory="أُرسل أو تطوّع لمراقبة هذه المجموعة تحديدًا.",
        public_goal="الظهور بمظهر لاعب عادي كباقي الحاضرين.",
        secret_goal="جمع أكبر قدر من المعلومات الحساسة دون كشف طبيعة مهمتك.",
        secret_template="أنت هنا فعليًا لمراقبة شخص أو موقف محدد، وليس بمحض الصدفة.",
        ability_name="معلومة محدودة",
        ability_description="يحصل على معلومة محدودة عن لاعب مستهدف.",
        ability_type="spy_info", ability_uses=3, needs_target=True,
        weakness="كثرة استخدامك لهذه القدرة قد تكشف نمطًا يلاحظه المراقبون الآخرون.",
        initial_info="تعرف أن هناك ما يستحق المراقبة في هذا المكان تحديدًا.",
        possible_relations=["stranger", "impostor"],
        side_quest="اجمع معلومات عن ثلاثة لاعبين مختلفين على الأقل دون أن تُكتشف.",
        tier="chaotic",
    ),
    Role(
        id="liar", name="الكذاب", emoji="🎭",
        description="يجيد الحديث بثقة، حتى حين لا يملك الحقيقة كاملة.",
        backstory="اعتاد أن يفلت من مواقف حرجة بلباقته اللفظية.",
        public_goal="الظهور بمظهر صادق وموثوق أمام الجميع.",
        secret_goal="إقناع المجموعة بكذبة واحدة محورية قبل نهاية اللعبة.",
        secret_template="عليك أن تُقنع المجموعة في مرحلة ما بشيء غير صحيح دون أن يكتشفوا ذلك لاحقًا.",
        ability_name="ثقة مصطنعة",
        ability_description="يقلل احتمال أن تُكتشف إحدى تصريحاته كاذبة في هذه الجولة (تأثير سردي).",
        ability_type="passive", ability_uses=0, needs_target=False,
        weakness="إن انكشفت كذبة واحدة بوضوح، ستتم مراجعة كل ما قلته سابقًا بالشك.",
        initial_info="تعرف كيف تصوغ كلامك ليبدو مقنعًا حتى دون دليل.",
        possible_relations=["impostor", "traitor"],
        side_quest="أقنع شخصًا واحدًا على الأقل بشيء غير دقيق دون أن يكتشف ذلك فورًا.",
        tier="chaotic",
    ),
    Role(
        id="judge", name="القاضي", emoji="⚖️",
        description="يزن الكلام بميزان صارم قبل أن يقتنع بأي شيء.",
        backstory="اعتاد إصدار أحكام يعتمد عليها الآخرون في مواقف سابقة.",
        public_goal="توجيه القرارات الجماعية نحو ما يبدو أكثر عدلًا ومنطقية.",
        secret_goal="التأثير على قرار واحد محدد بما يخدم قناعتك الشخصية.",
        secret_template="لديك قناعة شخصية راسخة تجاه أحد الحاضرين لم تُبنَ بالكامل على دليل.",
        ability_name="ترجيح قرار",
        ability_description="يمنح ملاحظته وزنًا إضافيًا يؤثر على صياغة القرار الجماعي القادم.",
        ability_type="influence_decision", ability_uses=1, needs_target=False,
        weakness="قناعتك الشخصية قد تكون متحيزة دون أن تدرك ذلك بنفسك.",
        initial_info="تميل لتكوين رأي حاسم بسرعة أكبر من بقية الحاضرين.",
        possible_relations=["mediator", "neutral_voice"],
        side_quest="أثّر في قرار جماعي واحد بطريقة حاسمة وواضحة.",
        tier="support",
    ),
    Role(
        id="oracle", name="العراف", emoji="🔮",
        description="يشعر أحيانًا بما هو قادم قبل أن يحدث فعلًا.",
        backstory="لطالما وُصف بأن حدسه غريب الدقة أحيانًا.",
        public_goal="مشاركة حدسه دون أن يبدو غامضًا أكثر من اللازم.",
        secret_goal="التأكد ما إذا كان حدسك هذه المرة صحيحًا أم مجرد قلق شخصي.",
        secret_template="راودك شعور غامض تجاه ما سيحدث قبل أن يقع فعلًا، ولا تعرف مصدره.",
        ability_name="تلميح غامض",
        ability_description="يحصل على تلميح غامض غير مؤكد عن اتجاه الجولة القادمة.",
        ability_type="reveal_hint", ability_uses=1, needs_target=False,
        weakness="تلميحاتك غامضة عمدًا وقد تُفهم بشكل معاكس تمامًا لما قصدته.",
        initial_info="تشعر بأن جزءًا واحدًا من هذه القصة سيتكرر لاحقًا بشكل مختلف.",
        possible_relations=["witness", "secret_holder"],
        side_quest="شارك تلميحًا واحدًا يتحقق لاحقًا بطريقة ما.",
        tier="support",
    ),
    Role(
        id="keeper_of_secrets", name="حارس الأسرار", emoji="🤫",
        description="يُؤتمن على أكثر مما يستحقه ظاهره الهادئ.",
        backstory="الناس يميلون لإخباره أشياء لا يخبرونها لغيره.",
        public_goal="أن يظل موضع ثقة الجميع في آن واحد.",
        secret_goal="حماية سرّ لاعب آخر تعهدت بعدم كشفه مهما حدث.",
        secret_template="تعهدت لأحد الحاضرين بحماية سرّه، وهذا يقيّد ما يمكنك قوله بحرية.",
        ability_name="حماية سرّ",
        ability_description="يمنع سرًا محددًا من أن يُكشف تلقائيًا هذه الجولة.",
        ability_type="protect", ability_uses=2, needs_target=True,
        weakness="التزامك بحماية سرّ الآخرين قد يجعلك تبدو متكتمًا أو مريبًا أمام الباقين.",
        initial_info="تحمل ثقة شخص واحد على الأقل منذ بداية اللقاء.",
        possible_relations=["secret_holder", "secret_partner"],
        side_quest="حافظ على السرّ الذي تحميه حتى الجولة الأخيرة دون أن ينكشف بفعلك.",
        tier="support",
    ),
    Role(
        id="expert", name="الخبير", emoji="🧪",
        description="يتعامل مع التفاصيل الفنية والتقنية بدقة أكبر من غيره.",
        backstory="خبرته المهنية السابقة تجعله يرى ما يفوت الآخرين.",
        public_goal="تقديم تحليل تقني دقيق يخدم التحقيق الجماعي.",
        secret_goal="التأكد أن تحليلك الفني هو ما يُبنى عليه القرار النهائي.",
        secret_template="لاحظت تفصيلًا فنيًا دقيقًا لم يلاحظه أحد بعد، ولم تفصح عنه كاملًا بعد.",
        ability_name="تحليل معملي",
        ability_description="يحلل دليلًا بدقة عالية ويكشف جانبًا تقنيًا فيه لم يكن واضحًا.",
        ability_type="analyze_evidence", ability_uses=2, needs_target=False,
        weakness="تحليلك الفني الدقيق قد يفوّت البعد الإنساني أو النفسي للموقف.",
        initial_info="تُجيد قراءة التفاصيل الدقيقة في أي دليل ماديّ.",
        possible_relations=["researcher", "genius"],
        side_quest="قدّم تحليلًا فنيًا واحدًا يغيّر تفسير دليل قائم بالكامل.",
        tier="support",
    ),
    Role(
        id="historian", name="المؤرخ", emoji="📖",
        description="يتذكر التفاصيل القديمة بدقة أكبر من تذكره للحاضر أحيانًا.",
        backstory="مهتم دومًا بجذور أي حدث أكثر من اهتمامه بنتيجته المباشرة.",
        public_goal="ربط الحاضر بجذوره الماضية لفهم أعمق للقصة.",
        secret_goal="إثبات أن الماضي هو المفتاح الحقيقي لحل هذه القضية.",
        secret_template="تعرف تفصيلًا قديمًا عن هذا المكان أو هؤلاء الأشخاص لم يُذكر بعد في النقاش الحالي.",
        ability_name="استحضار ذاكرة",
        ability_description="يستحضر معلومة من جولة سابقة قد تكون نُسيت أو أُهملت.",
        ability_type="recall_memory", ability_uses=2, needs_target=False,
        weakness="تركيزك الشديد على الماضي قد يجعلك تتأخر في ملاحظة تطورات الحاضر.",
        initial_info="تحتفظ بتفاصيل الجولات السابقة أدق من بقية الحاضرين.",
        possible_relations=["silent_narrator", "secret_holder"],
        side_quest="اربط حدثًا حاليًا بتفصيل من جولة سابقة نُسي إلى حد ما.",
        tier="support",
    ),
    Role(
        id="thief", name="السارق", emoji="🗝️",
        description="يجيد الحصول على ما يريد دون أن يُطلب منه ذلك مباشرة.",
        backstory="اعتاد أن يحصل على المعلومات بطرق غير تقليدية.",
        public_goal="البقاء بمظهر عادي رغم ما يجمعه من معلومات فعليًا.",
        secret_goal="جمع معلومة أو دليل يخص لاعبًا آخر دون علمه.",
        secret_template="حصلت على شيء لا يخصك بالكامل، وتحتفظ به دون أن يعرف صاحبه الأصلي.",
        ability_name="سرقة معلومة",
        ability_description="يسرق تفصيلًا واحدًا من معلومات لاعب مستهدف (لا يكشف سرّه الكامل).",
        ability_type="steal_info", ability_uses=2, needs_target=True,
        weakness="إن انكشف أنك سرقت معلومة من أحدهم، ستفقد ثقته بالكامل فورًا.",
        initial_info="تعرف كيف تحصل على ما تريد دون طلبه مباشرة.",
        possible_relations=["impostor", "spy"],
        side_quest="اسرق معلومة واحدة على الأقل دون أن يكتشف صاحبها ذلك.",
        tier="chaotic",
    ),
    Role(
        id="impostor", name="المنتحل", emoji="👤",
        description="ليس بالضرورة من يقول إنه هو.",
        backstory="له سبب وجيه (في نظره) لإخفاء هويته الحقيقية هنا.",
        public_goal="الحفاظ على الهوية التي قدّم نفسه بها للمجموعة.",
        secret_goal="عدم انكشاف هويتك أو نيتك الحقيقية حتى النهاية.",
        secret_template="ما قدّمته عن نفسك للمجموعة ليس دقيقًا بالكامل، ولديك سبب لذلك.",
        ability_name="تقليد قدرة",
        ability_description="يستخدم مرة واحدة تأثيرًا عامًا شبيهًا بقدرة تحقيق أو مراقبة بسيطة.",
        ability_type="analyze_evidence", ability_uses=1, needs_target=False,
        weakness="أي سؤال مباشر ودقيق عن ماضيك قد يكشف الفجوة في قصتك.",
        initial_info="تعرف أن هويتك المعلنة لن تصمد أمام تدقيق شديد.",
        possible_relations=["stranger", "traitor"],
        side_quest="حافظ على قصتك المعلنة متماسكة حتى الجولة الأخيرة.",
        tier="chaotic",
    ),
    Role(
        id="secret_partner", name="الشريك السري", emoji="🤝",
        description="مرتبط بلاعب آخر برباط لا يعرفه بقية الحاضرين.",
        backstory="جمعتكما تجربة أو اتفاق سابق قبل هذه الأحداث.",
        public_goal="التصرف وكأنك لا تعرف شريكك أكثر من بقية الحاضرين.",
        secret_goal="حماية شريكك السري وتحقيق هدف مشترك بينكما.",
        secret_template="ترتبط بأحد الحاضرين باتفاق أو معرفة سابقة لم يعلمها أحد غيركما.",
        ability_name="تنسيق صامت",
        ability_description="يرسل ملاحظة صغيرة إلى شريكه المفترض دون أن يعرف بقية اللاعبين بذلك.",
        ability_type="spy_info", ability_uses=2, needs_target=True,
        weakness="أي تصرف متزامن جدًا بينك وبين شريكك قد يلفت الانتباه لوجود رابط بينكما.",
        initial_info="تعرف من هو الشخص الآخر المرتبط بك في هذه القصة.",
        possible_relations=["mediator", "keeper_of_secrets"],
        side_quest="حقق هدفًا مشتركًا واحدًا مع شريكك دون أن يُكتشف ارتباطكما.",
        tier="narrative",
    ),
    Role(
        id="puzzle_solver", name="حلال الألغاز", emoji="🧩",
        description="يحب تجميع القطع المتناثرة أكثر من حبه للنقاش الطويل.",
        backstory="اعتاد حل الألغاز والأحاجي منذ الصغر، وهذا الموقف أشبه بلغز كبير.",
        public_goal="تجميع القطع المتفرقة في صورة واحدة مفهومة.",
        secret_goal="حل اللغز المحوري بنفسك قبل أن يتوصل إليه أي شخص آخر.",
        secret_template="تشعر أن هناك نمطًا خفيًا يربط كل ما يحدث، ولم تكشف تفاصيله بعد.",
        ability_name="تلميح لغز",
        ability_description="يحصل على تلميح إضافي يساعد في حل لغز أو نمط جماعي قائم.",
        ability_type="puzzle_hint", ability_uses=2, needs_target=False,
        weakness="هوسك بإيجاد نمط قد يجعلك ترى روابط غير موجودة فعليًا.",
        initial_info="تلاحظ الأنماط المتكررة أسرع من بقية الحاضرين.",
        possible_relations=["researcher", "genius"],
        side_quest="اربط ثلاث تفاصيل متفرقة في نمط واحد متماسك.",
        tier="support",
    ),
    Role(
        id="chaos_maker", name="صانع الفوضى", emoji="🕸️",
        description="يزدهر وسط الشك المتبادل بين الآخرين.",
        backstory="يرى أن الحقيقة الواحدة الواضحة مملة، ويفضّل تعدد الاحتمالات.",
        public_goal="إبقاء النقاش حيًا ومثيرًا مهما كلّف ذلك من وضوح.",
        secret_goal="زرع أكبر قدر من الشك المتبادل دون أن يُكتشف أنك مصدره.",
        secret_template="تستمتع سرًا بمشاهدة الآخرين يشكّون ببعضهم، وتساهم في ذلك بهدوء متعمد.",
        ability_name="نشر إشاعة",
        ability_description="ينشر تفصيلًا غير مؤكد يضاف إلى الأدلة المتداولة كدليل مضلل محتمل.",
        ability_type="propagate_rumor", ability_uses=2, needs_target=False,
        weakness="إن انكشف أنك مصدر إشاعة واحدة كاذبة، سيُعاد فحص كل ما قلته بعين الشك.",
        initial_info="تعرف كيف تصوغ شكًا صغيرًا يكبر وحده مع الوقت.",
        possible_relations=["liar", "traitor"],
        side_quest="زرع شكًا واحدًا بين لاعبين لم يكونا متشاكّين ببعضهما من قبل.",
        tier="chaotic",
    ),
]

ROLES_BY_ID: Dict[str, Role] = {r.id: r for r in ROLES}

# سقف عدد الأدوار "الفوضوية" (تضليل/خداع) في المباراة الواحدة، حسب عدد
# اللاعبين، حتى لا تطغى على توازن اللعبة.
_CHAOTIC_TIER = "chaotic"


def _chaotic_cap(player_count: int) -> int:
    return max(1, player_count // 5)


async def assign_roles(chat_id: int, player_count: int, difficulty: str = "medium") -> List[Role]:
    """يختار قائمة أدوار بعدد اللاعبين، متوازنة وغير مكررة قدر الإمكان عبر
    مباريات متتالية لنفس المجموعة (يتجنب ما استُخدم مؤخرًا عبر جدول
    used_content، بنفس أسلوب variety.py)."""
    recently_used = set(await db.get_recently_used(chat_id, "role", limit=max(10, player_count * 2)))

    pool = [r for r in ROLES if r.id not in recently_used] or list(ROLES)
    random.shuffle(pool)

    chosen: List[Role] = []
    chaotic_count = 0
    cap = _chaotic_cap(player_count)

    for role in pool:
        if len(chosen) >= player_count:
            break
        if role.tier == _CHAOTIC_TIER:
            if chaotic_count >= cap:
                continue
            chaotic_count += 1
        chosen.append(role)

    # إن لم يكفِ التجنب لملء العدد المطلوب (مجموعة صغيرة استُخدمت فيها كل
    # الأدوار غير الفوضوية مؤخرًا)، أكمل من كامل القائمة مع احترام السقف.
    if len(chosen) < player_count:
        remaining_pool = [r for r in ROLES if r not in chosen]
        random.shuffle(remaining_pool)
        for role in remaining_pool:
            if len(chosen) >= player_count:
                break
            if role.tier == _CHAOTIC_TIER and chaotic_count >= cap:
                continue
            if role.tier == _CHAOTIC_TIER:
                chaotic_count += 1
            chosen.append(role)

    random.shuffle(chosen)
    for role in chosen:
        await db.mark_used(chat_id, "role", role.id)
    return chosen


def get_role(role_id: str) -> Optional[Role]:
    return ROLES_BY_ID.get(role_id)


def role_card_text(role: Role) -> str:
    """يبني نص بطاقة الدور الكاملة التي تُرسل للاعب في الخاص."""
    ability_line = (
        f"لا توجد قدرة فعّالة تُستخدم يدويًا لهذا الدور (تأثيره سردي دائم)."
        if role.ability_type == "passive"
        else f"{role.ability_description}\n"
        f"عدد الاستخدامات المتاحة: {role.ability_uses}"
        + (" (تحتاج اختيار هدف)" if role.needs_target else "")
    )
    return (
        f"{role.emoji} **دورك: {role.name}**\n\n"
        f"📝 {role.description}\n\n"
        f"📖 *خلفيتك:* {role.backstory}\n\n"
        f"🎯 *هدفك العلني:* {role.public_goal}\n"
        f"🎯 *هدفك السرّي:* {role.secret_goal}\n\n"
        f"⚡ *قدرتك الخاصة — {role.ability_name}:*\n{ability_line}\n\n"
        f"⚠️ *نقطة ضعفك:* {role.weakness}\n\n"
        f"ℹ️ *معلومة أولية:* {role.initial_info}\n\n"
        f"🧩 *مهمة جانبية:* {role.side_quest}\n\n"
        f"استخدم /ability في محادثتنا الخاصة هذه لاستخدام قدرتك عند الحاجة، "
        f"و/myrole لعرض هذه البطاقة مجددًا في أي وقت."
    )
