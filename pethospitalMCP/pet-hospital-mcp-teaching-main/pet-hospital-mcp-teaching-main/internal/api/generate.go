package api

import (
	"fmt"
	"math/rand"
	"time"

	"pethospital/internal/model"
)

// ---------------------------------------------------------------------------
// 大批量模拟数据生成器
//
// 使用固定种子的伪随机数，保证每次生成的“随机”数据完全一致 —— 便于复现、
// 便于对比测试结果。
// ---------------------------------------------------------------------------

// 宠物名字池（按种类区分，更贴近真实命名习惯）
var namePools = map[string][]string{
	model.SpeciesDog:     {"旺财", "豆豆", "大金", "球球", " Lucky", "阿黄", "虎子", "元宝", "可乐", "布丁", "闪电", "将军", "多多", "包子", "墩墩", "土豆", "花卷", "芝麻", "糯米", "桃酥", "麦芽", "陈皮", "山楂", "阿福", "来福", "小七", "旋风", "饼干", "馒头", "汤圆", "核桃", "南瓜", "豆芽", "椰子", "栗子"},
	model.SpeciesCat:     {"咪咪", "团子", "雪球", "奶昔", "tiger", "花猫", "小黑", "橘座", "布丁", "可可", "果冻", "棉花", "奶糖", "小鱼", "鱼丸", "芝士", "拿铁", "摩卡", "可乐", "月饼", "豆沙", "蛋黄", "泡芙", "奶盖", "年糕", "芋圆", "汤圆", "桃子", "柚子", "柠檬", "山楂", "陈皮", "curry", "豆皮", "小米"},
	model.SpeciesRabbit:  {"雪球", "白白", "灰灰", "跳跳", "棉花糖", "胡萝卜", "萝卜", "蹦蹦", "糯米", "奶冻", "小灰", "团子", "月亮", "云朵", "雪糕"},
	model.SpeciesBird:    {"皮皮", "小黄", "啾啾", "阿蓝", "翠翠", "啾宝", "金豆", "小翠", "闹闹", "唱唱", "毛毛", "小鹉", "阿绿", "点点"},
	model.SpeciesHamster: {"小白", "球球", "布丁", "奶酪", "瓜子", "芝麻", "汤圆", "花生", "豆豆", "小胖", "圆滚滚"},
	model.SpeciesReptile: {"青龙", "小绿", "盔甲", "蜥蜥", "阿鬃", "石头", "闪电", "铠甲"},
	model.SpeciesOther:   {"小可爱", "宝贝", "毛毛", "豆豆", "团团", "圆圆"},
}

// 品种池
var breedPools = map[string][]string{
	model.SpeciesDog:     {"金毛寻回犬", "柯基", "拉布拉多", "边牧", "泰迪", "比熊", "哈士奇", "萨摩耶", "柴犬", "博美", "雪纳瑞", "吉娃娃", "中华田园犬", "德国牧羊犬", "阿拉斯加"},
	model.SpeciesCat:     {"英国短毛猫", "布偶猫", "暹罗猫", "美国短毛猫", "加菲猫", "缅因猫", "橘猫", "狸花猫", "波斯猫", "孟买猫", "斯芬克斯无毛猫", "金吉拉"},
	model.SpeciesRabbit:  {"垂耳兔", "侏儒兔", "狮子兔", "安哥拉兔", "新西兰兔", "道奇兔"},
	model.SpeciesBird:    {"玄凤鹦鹉", "虎皮鹦鹉", "牡丹鹦鹉", "和尚鹦鹉", "金太阳鹦鹉", "八哥", "文鸟", "文须雀"},
	model.SpeciesHamster: {"布丁仓鼠", "金丝熊", "三线仓鼠", "银狐仓鼠", "罗伯罗夫斯基仓鼠", "奶茶仓鼠"},
	model.SpeciesReptile: {"绿鬣蜥", "豹纹守宫", "玉米蛇", "球蟒", "巴西龟", "苏卡达陆龟", "蓝舌石龙子"},
	model.SpeciesOther:   {"荷兰猪", "龙猫", "刺猬", "蜜袋鼯", "宠物猪"},
}

// 毛色池
var colorPools = map[string][]string{
	model.SpeciesDog:     {"金黄", "奶白", "三色", "黑白", "棕红", "灰白", "纯黑", "奶油色", "陨石色"},
	model.SpeciesCat:     {"蓝灰", "海豹双色", "橘白", "纯白", "狸花", "黑白奶牛", "玳瑁", "银渐层", "金渐层"},
	model.SpeciesRabbit:  {"白", "灰", "黑白花", "奶油", "巧克力", "蓝色"},
	model.SpeciesBird:    {"黄灰", "翠绿", "宝蓝", "纯白", "柠檬黄", "橙红"},
	model.SpeciesHamster: {"奶油", "金黄", "灰白", "纯白", "黑熊色"},
	model.SpeciesReptile: {"翠绿", "褐色", "砂黄", "墨绿", "灰蓝"},
	model.SpeciesOther:   {"白色", "棕色", "花色", "灰色"},
}

// 疾病池（含对应科室与常见处置，尽量贴近真实兽医临床）
type diseaseTemplate struct {
	Name         string
	Category     string // 疾病大类
	Symptoms     []string
	Treatment    []string
	Prescription []string
	Severity     int // 1=轻 2=中 3=重，影响费用与状态
}

// 物种限定：把明显只适用于某类动物的疾病挑出来，避免生成
// 「仓鼠股骨骨折」「鹦鹉犬瘟热」这类不合常理的组合。
// 键为疾病名，值为允许的种类（空表示不限）。
var speciesLimited = map[string][]string{
	// 犬猫专属（体型 / 生理结构决定的疾病）
	"髋关节发育不良":  sppDog,
	"前十字韧带断裂":  sppDog,
	"椎间盘突出":    sppDogCat,
	"股骨骨折":     sppDogCat,
	"猫鼻支":      sppCat,
	"猫下泌尿道综合征": sppCat,
	"犬窝咳":      sppDog,
	"犬细小病毒感染":  sppDog,
	"犬瘟热":      sppDog,
	"传染性肝炎":    sppDog,
	"钩端螺旋体病":   sppDog,
	"心丝虫":      sppDogCat,
	"子宫蓄脓":     sppDogCat,
	"膀胱结石":     sppDogCat,
	"糖尿病":      sppDogCat,
	"甲状腺功能减退":  sppDogCat,
	"白内障":      sppDogCat,
	"癫痫":       sppDogCat,
	"中暑":       sppDogCat,
	"肥胖症":      sppDogCat,

	// 猫科专属
	"猫瘟": sppCat,

	// 以犬猫为主（在小宠/鸟类上极罕见，不做泛化以保证数据严谨）
	"胰腺炎":   sppDogCat,
	"慢性肾病":  sppDogCat,
	"支气管炎":  sppDogCat,
	"前庭综合征": sppDogCat,
	"过敏性皮炎": sppDogCat,
	"角膜溃疡":  sppDogCat,
	"脓皮症":   sppDogCat,
	"耳螨":    sppDogCat,

	// 小宠 / 异宠专属
	"湿尾症":        sppSmall,
	"球虫病":        sppSmall,
	"牙科疾病（牙齿过长）": sppSmall,
	"代谢性骨病":      sppReptile,
	"脱肛":         sppSmall,
	"羽毛啄癖":       sppBird,

	// 通用疾病（不含在上面）保持不限，如肠胃炎、皮肤病、寄生虫等
}

// 物种组合常量
var (
	sppDog     = []string{model.SpeciesDog}
	sppCat     = []string{model.SpeciesCat}
	sppDogCat  = []string{model.SpeciesDog, model.SpeciesCat}
	sppSmall   = []string{model.SpeciesRabbit, model.SpeciesHamster, model.SpeciesOther}
	sppBird    = []string{model.SpeciesBird}
	sppReptile = []string{model.SpeciesReptile}
)

// pickDiseaseFor 为指定种类挑选一只合适的疾病。
func pickDiseaseFor(rng *rand.Rand, species string) diseaseTemplate {
	candidates := make([]diseaseTemplate, 0, len(diseasePool))
	for _, d := range diseasePool {
		allowed, limited := speciesLimited[d.Name]
		if !limited {
			candidates = append(candidates, d)
			continue
		}
		for _, s := range allowed {
			if s == species {
				candidates = append(candidates, d)
				break
			}
		}
	}
	if len(candidates) == 0 {
		return diseasePool[rng.Intn(len(diseasePool))]
	}
	return candidates[rng.Intn(len(candidates))]
}

var diseasePool = []diseaseTemplate{
	// --- 消化系统 ---
	{Name: "急性肠胃炎", Category: "消化系统", Symptoms: []string{"呕吐", "腹泻", "食欲不振", "精神萎靡"}, Treatment: []string{"静脉补液 + 消炎", "禁食 12 小时后少量流食", "止吐 + 胃肠黏膜保护"}, Prescription: []string{"阿莫西林克拉维酸钾", "蒙脱石散", "益生菌", "止吐针"}, Severity: 2},
	{Name: "胰腺炎", Category: "消化系统", Symptoms: []string{"剧烈腹痛", "反复呕吐", "弓背姿势", "拒食"}, Treatment: []string{"禁食 + 静脉营养", "镇痛 + 抑酶", "纠正电解质紊乱"}, Prescription: []string{"乌司他丁", "布托啡诺", "乳酸林格液"}, Severity: 3},
	{Name: "异物梗阻", Category: "消化系统", Symptoms: []string{"干呕", "无法进食", "腹部触诊敏感"}, Treatment: []string{"内镜取物", "开腹手术取出异物", "术后禁食观察"}, Prescription: []string{"头孢曲松", "奥美拉唑", "术后止痛药"}, Severity: 3},
	{Name: "便秘", Category: "消化系统", Symptoms: []string{"排便困难", "努责", "腹部胀满"}, Treatment: []string{"灌肠 + 软化粪便", "增加饮水与纤维"}, Prescription: []string{"乳果糖", "膳食纤维粉"}, Severity: 1},
	{Name: "牙周炎", Category: "口腔", Symptoms: []string{"口臭", "流涎", "进食疼痛", "牙龈红肿"}, Treatment: []string{"超声波洁牙", "拔除松动牙齿", "口腔抗菌冲洗"}, Prescription: []string{"甲硝唑", "口腔护理凝胶"}, Severity: 2},

	// --- 呼吸系统 ---
	{Name: "猫鼻支", Category: "呼吸系统", Symptoms: []string{"打喷嚏", "眼鼻分泌物增多", "结膜充血", "发热"}, Treatment: []string{"抗病毒滴眼液 + 口服赖氨酸", "雾化吸入", "鼻腔冲洗"}, Prescription: []string{"泛昔洛韦滴眼液", "L-赖氨酸", "猫干扰素"}, Severity: 2},
	{Name: "犬窝咳", Category: "呼吸系统", Symptoms: []string{"阵发性干咳", "运动后咳嗽加重", "咳出白色泡沫"}, Treatment: []string{"止咳 + 抗菌", "避免剧烈运动", "雾化"}, Prescription: []string{"多西环素", "氨溴索", "止咳糖浆"}, Severity: 2},
	{Name: "肺炎", Category: "呼吸系统", Symptoms: []string{"高热", "呼吸急促", "鼻翼扇动", "精神沉郁"}, Treatment: []string{"吸氧 + 静脉抗生素", "雾化排痰", "住院监护"}, Prescription: []string{"头孢噻呋", "氨溴索", "地塞米松"}, Severity: 3},
	{Name: "支气管炎", Category: "呼吸系统", Symptoms: []string{"持续性咳嗽", "喘息", "活动耐力下降"}, Treatment: []string{"支气管扩张剂 + 抗炎", "环境除螨"}, Prescription: []string{"泼尼松龙", "茶碱", "氨溴索"}, Severity: 2},

	// --- 皮肤病 ---
	{Name: "皮肤真菌感染", Category: "皮肤", Symptoms: []string{"局部脱毛", "皮屑增多", "皮肤发红", "环形脱毛斑"}, Treatment: []string{"外用药 + 药浴", "口服抗真菌药", "环境消毒"}, Prescription: []string{"特比萘芬", "药浴液", "伊曲康唑"}, Severity: 2},
	{Name: "螨虫感染", Category: "皮肤", Symptoms: []string{"剧烈瘙痒", "耳廓增厚", "皮肤结痂", "频繁抓挠"}, Treatment: []string{"体外驱虫", "药浴", "继发感染抗菌"}, Prescription: []string{"塞拉菌素", "双甲脒药浴", "头孢氨苄"}, Severity: 2},
	{Name: "过敏性皮炎", Category: "皮肤", Symptoms: []string{"全身瘙痒", "皮肤红斑", "反复舔舐腹部"}, Treatment: []string{"抗组胺 + 低敏处方粮", "避免过敏原", "药浴"}, Prescription: []string{"氯雷他定", "低敏处方粮", "必需脂肪酸"}, Severity: 1},
	{Name: "脓皮症", Category: "皮肤", Symptoms: []string{"皮肤脓疱", "脱毛", "异味", "表皮溃烂"}, Treatment: []string{"全身抗生素 4 周", "抗菌药浴", "局部清创"}, Prescription: []string{"头孢氨苄", "氯己定药浴液"}, Severity: 2},
	{Name: "耳螨", Category: "皮肤", Symptoms: []string{"频繁甩头", "耳道黑色分泌物", "耳廓抓伤"}, Treatment: []string{"耳道清洗 + 滴耳", "体外驱虫"}, Prescription: []string{"耳肤灵", "塞拉菌素"}, Severity: 1},

	// --- 骨科 / 外科 ---
	{Name: "股骨骨折", Category: "骨科", Symptoms: []string{"患肢无法着地", "明显疼痛", "局部肿胀"}, Treatment: []string{"内固定手术 + 术后制动", "外固定支架", "术后康复训练"}, Prescription: []string{"美洛昔康", "头孢氨苄", "钙片"}, Severity: 3},
	{Name: "髋关节发育不良", Category: "骨科", Symptoms: []string{"起立困难", "运动后跛行", "后肢无力"}, Treatment: []string{"关节保护药物 + 控制体重 + 水疗", "必要时全髋置换"}, Prescription: []string{"关节软骨素", "鱼油", "止痛药"}, Severity: 2},
	{Name: "前十字韧带断裂", Category: "骨科", Symptoms: []string{"突发跛行", "膝关节不稳", "坐姿异常"}, Treatment: []string{"TPLO 手术", "术后制动 6 周", "康复理疗"}, Prescription: []string{"美洛昔康", "加巴喷丁"}, Severity: 3},
	{Name: "椎间盘突出", Category: "骨科", Symptoms: []string{"背部疼痛", "后肢共济失调", "严重时瘫痪"}, Treatment: []string{"严格笼养静养", "脱水减压", "重症手术减压"}, Prescription: []string{"甲泼尼龙", "加巴喷丁", "维生素 B12"}, Severity: 3},
	{Name: "软组织撕裂伤", Category: "外科", Symptoms: []string{"皮肤裂口", "出血", "创面污染"}, Treatment: []string{"清创缝合", "破伤风预防", "换药"}, Prescription: []string{"头孢唑林", "碘伏", "止痛药"}, Severity: 2},
	{Name: "膀胱结石", Category: "泌尿", Symptoms: []string{"排尿困难", "血尿", "频繁蹲厕"}, Treatment: []string{"手术取石", "处方粮溶石", "增加饮水"}, Prescription: []string{"泌尿处方粮", "头孢氨苄"}, Severity: 3},

	// --- 泌尿 / 生殖 ---
	{Name: "猫下泌尿道综合征", Category: "泌尿", Symptoms: []string{"排尿疼痛", "血尿", "在猫砂盆外排尿", "尿闭"}, Treatment: []string{"导尿 + 冲洗", "解痉 + 抗炎", "改喂处方粮"}, Prescription: []string{"泌尿处方粮", "阿米替林", "哌唑嗪"}, Severity: 3},
	{Name: "慢性肾病", Category: "泌尿", Symptoms: []string{"多饮多尿", "体重下降", "口腔溃疡", "食欲减退"}, Treatment: []string{"肾脏处方粮", "皮下补液", "控制磷摄入"}, Prescription: []string{"肾脏处方粮", "碳酸镧", "贝那普利"}, Severity: 3},
	{Name: "子宫蓄脓", Category: "生殖", Symptoms: []string{"腹部膨大", "阴道分泌物", "发热", "精神沉郁"}, Treatment: []string{"紧急手术切除子宫", "术前补液稳定", "术后抗感染"}, Prescription: []string{"头孢曲松", "甲硝唑"}, Severity: 3},

	// --- 传染病 ---
	{Name: "猫瘟", Category: "传染病", Symptoms: []string{"高热", "精神沉郁", "拒食", "呕吐"}, Treatment: []string{"隔离住院 + 抗病毒血清 + 补液", "升白细胞治疗", "严格消毒"}, Prescription: []string{"猫瘟单抗", "干扰素", "葡萄糖注射液", "止吐针"}, Severity: 3},
	{Name: "犬细小病毒感染", Category: "传染病", Symptoms: []string{"剧烈呕吐", "血便", "脱水", "白细胞下降"}, Treatment: []string{"隔离 + 静脉补液", "抗病毒血清", "止吐止血"}, Prescription: []string{"犬细小单抗", "干扰素", "止血敏", "乳酸林格液"}, Severity: 3},
	{Name: "犬瘟热", Category: "传染病", Symptoms: []string{"双相热", "脓性眼鼻分泌物", "脚垫增厚", "神经症状"}, Treatment: []string{"对症支持治疗", "抗病毒 + 抗继发感染", "营养支持"}, Prescription: []string{"犬瘟单抗", "头孢曲松", "维生素 B 族"}, Severity: 3},
	{Name: "传染性肝炎", Category: "传染病", Symptoms: []string{"发热", "角膜浑浊", "腹痛", "呕吐"}, Treatment: []string{"保肝 + 补液", "抗病毒", "支持疗法"}, Prescription: []string{"腺苷蛋氨酸", "水飞蓟素", "葡萄糖"}, Severity: 3},
	{Name: "钩端螺旋体病", Category: "传染病", Symptoms: []string{"高热", "黄疸", "肌肉疼痛", "血尿"}, Treatment: []string{"青霉素类抗生素", "补液保肝", "隔离消毒"}, Prescription: []string{"氨苄西林", "多西环素"}, Severity: 3},

	// --- 寄生虫 ---
	{Name: "蛔虫感染", Category: "寄生虫", Symptoms: []string{"腹部膨大", "消瘦", "腹泻", "粪便见虫体"}, Treatment: []string{"体内驱虫", "环境消毒", "定期预防"}, Prescription: []string{"米尔贝肟", "芬苯达唑"}, Severity: 1},
	{Name: "球虫病", Category: "寄生虫", Symptoms: []string{"腹泻带血", "消瘦", "精神不振"}, Treatment: []string{"抗球虫药", "补充电解质", "清洁笼具"}, Prescription: []string{"妥曲珠利", "电解质粉"}, Severity: 2},
	{Name: "心丝虫", Category: "寄生虫", Symptoms: []string{"运动不耐受", "咳嗽", "腹水", "消瘦"}, Treatment: []string{"分阶段杀虫", "严格限制运动", "对症支持"}, Prescription: []string{"美拉索明", "多西环素"}, Severity: 3},

	// --- 眼科 / 神经 ---
	{Name: "角膜溃疡", Category: "眼科", Symptoms: []string{"畏光", "流泪", "角膜浑浊", "频繁眨眼"}, Treatment: []string{"抗生素眼药水", "佩戴伊丽莎白圈", "促进角膜修复"}, Prescription: []string{"妥布霉素滴眼液", "自体血清滴眼液"}, Severity: 2},
	{Name: "白内障", Category: "眼科", Symptoms: []string{"瞳孔区发白", "行走碰撞", "视力下降"}, Treatment: []string{"手术摘除 + 人工晶体", "定期复查"}, Prescription: []string{"吡诺克辛滴眼液"}, Severity: 2},
	{Name: "癫痫", Category: "神经", Symptoms: []string{"全身抽搐", "口吐白沫", "意识丧失", "大小便失禁"}, Treatment: []string{"抗癫痫药物长期控制", "避免应激", "定期监测血药浓度"}, Prescription: []string{"苯巴比妥", "溴化钾"}, Severity: 3},
	{Name: "前庭综合征", Category: "神经", Symptoms: []string{"头部倾斜", "眼球震颤", "转圈", "平衡障碍"}, Treatment: []string{"对症支持", "止晕", "限制活动"}, Prescription: []string{"甲磺酸倍他司汀", "地塞米松"}, Severity: 2},

	// --- 内分泌 / 其他 ---
	{Name: "糖尿病", Category: "内分泌", Symptoms: []string{"多饮多尿", "体重下降", "食欲亢进", "白内障"}, Treatment: []string{"胰岛素治疗", "糖尿病处方粮", "定期监测血糖"}, Prescription: []string{"甘精胰岛素", "糖尿病处方粮"}, Severity: 3},
	{Name: "甲状腺功能减退", Category: "内分泌", Symptoms: []string{"嗜睡", "体重增加", "对称性脱毛", "怕冷"}, Treatment: []string{"甲状腺素替代治疗", "定期复查"}, Prescription: []string{"左旋甲状腺素"}, Severity: 2},
	{Name: "肥胖症", Category: "内分泌", Symptoms: []string{"体重超标", "活动减少", "易疲劳"}, Treatment: []string{"控制饮食 + 增加运动", "减重处方粮"}, Prescription: []string{"减重处方粮", "左旋肉碱"}, Severity: 1},
	{Name: "中暑", Category: "急诊", Symptoms: []string{"体温超过 41℃", "呼吸急促", "黏膜充血", "意识模糊"}, Treatment: []string{"紧急物理降温", "静脉补液", "吸氧监护"}, Prescription: []string{"乳酸林格液", "地塞米松"}, Severity: 3},
	{Name: "中毒（误食）", Category: "急诊", Symptoms: []string{"流涎", "呕吐", "抽搐", "瞳孔异常"}, Treatment: []string{"催吐 + 洗胃", "活性炭吸附", "对症解毒"}, Prescription: []string{"活性炭", "解毒剂", "止吐针"}, Severity: 3},
	{Name: "湿尾症", Category: "消化系统", Symptoms: []string{"尾部潮湿", "精神萎靡", "腹泻", "脱水"}, Treatment: []string{"口服抗生素 + 保温", "补充电解质", "更换垫料"}, Prescription: []string{"恩诺沙星滴剂", "电解质粉"}, Severity: 2},
	{Name: "羽毛啄癖", Category: "行为", Symptoms: []string{"羽毛大面积脱落", "自我啄羽", "皮肤损伤"}, Treatment: []string{"补充微量元素 + 环境丰容", "排查寄生虫与皮肤病"}, Prescription: []string{"鸟类综合维生素", "墨鱼骨"}, Severity: 1},
	{Name: "牙科疾病（牙齿过长）", Category: "口腔", Symptoms: []string{"流涎", "体重下降", "拒绝进食干草"}, Treatment: []string{"牙齿打磨 + 饮食调整", "定期复查"}, Prescription: []string{"提摩西草", "维生素 C 补充剂"}, Severity: 2},
	{Name: "代谢性骨病", Category: "骨科", Symptoms: []string{"四肢无力", "骨骼变形", "拒食"}, Treatment: []string{"补钙 + 补充 UVB 照射", "调整钙磷比"}, Prescription: []string{"钙粉", "维生素 D3"}, Severity: 2},
	{Name: "呼吸道感染", Category: "呼吸系统", Symptoms: []string{"张口呼吸", "鼻腔分泌物", "呼吸音粗"}, Treatment: []string{"抗生素 + 提高环境温度", "雾化"}, Prescription: []string{"恩诺沙星", "生理盐水雾化"}, Severity: 2},
	{Name: "脱肛", Category: "外科", Symptoms: []string{"肛门处脱出组织", "努责", "局部水肿"}, Treatment: []string{"手法复位 + 荷包缝合", "软化粪便", "减少刺激"}, Prescription: []string{"乳果糖", "头孢氨苄"}, Severity: 2},
}

// 收费项目模板
type chargeTemplate struct {
	Item     string
	Category string
	Min      float64
	Max      float64
}

var chargePool = []chargeTemplate{
	// 检查
	{"血常规检查", "检查", 120, 220},
	{"生化全项", "检查", 380, 680},
	{"血气分析", "检查", 260, 420},
	{"X 光检查（两张）", "检查", 300, 500},
	{"腹部 B 超", "检查", 300, 480},
	{"心脏彩超", "检查", 600, 900},
	{"粪常规 + 寄生虫镜检", "检查", 80, 160},
	{"尿常规", "检查", 80, 150},
	{"皮肤刮片镜检", "检查", 90, 180},
	{"真菌培养", "检查", 150, 280},
	{"犬细小抗原检测", "检查", 120, 220},
	{"犬瘟抗原检测", "检查", 120, 220},
	{"猫瘟抗原检测", "检查", 150, 260},
	{"猫呼吸道五联检测", "检查", 280, 420},
	{"猫白血病/艾滋筛查", "检查", 260, 400},
	{"心丝虫抗原检测", "检查", 180, 300},
	{"耳道镜检", "检查", 80, 150},
	{"眼压测量", "检查", 100, 180},
	{"CT 检查", "检查", 1500, 2600},
	{"MRI 检查", "检查", 2200, 3800},
	{"心电图", "检查", 260, 420},

	// 药品
	{"静脉输液", "药品", 120, 480},
	{"抗生素注射", "药品", 80, 320},
	{"止吐针", "药品", 60, 180},
	{"止痛针", "药品", 80, 240},
	{"驱虫药（体内）", "药品", 60, 180},
	{"体外驱虫滴剂", "药品", 90, 260},
	{"犬用益生菌", "药品", 80, 200},
	{"关节软骨素（1 疗程）", "药品", 500, 1100},
	{"猫瘟单抗", "药品", 800, 1600},
	{"犬细小单抗", "药品", 600, 1400},
	{"干扰素", "药品", 300, 700},
	{"白蛋白", "药品", 500, 1200},
	{"促红细胞生成素", "药品", 300, 700},
	{"甘精胰岛素", "药品", 260, 520},
	{"左旋甲状腺素", "药品", 180, 400},
	{"苯巴比妥", "药品", 120, 300},
	{"眼部抗生素滴眼液", "药品", 90, 220},
	{"耳肤灵", "药品", 120, 260},
	{"特比萘芬", "药品", 140, 320},
	{"伊曲康唑", "药品", 200, 450},
	{"外用抗真菌药", "药品", 100, 260},
	{"肾脏处方粮", "药品", 320, 620},
	{"泌尿处方粮", "药品", 300, 580},
	{"糖尿病处方粮", "药品", 300, 600},
	{"低敏处方粮", "药品", 280, 560},
	{"减重处方粮", "药品", 260, 520},
	{"鸟类综合维生素", "药品", 80, 200},
	{"恩诺沙星滴剂", "药品", 60, 160},
	{"钙粉 / 维生素 D3", "药品", 60, 180},

	// 手术
	{"麻醉费", "手术", 400, 1200},
	{"骨折内固定手术", "手术", 3800, 8800},
	{"全髋关节置换", "手术", 12000, 22000},
	{"TPLO 手术", "手术", 8000, 15000},
	{"椎间盘减压手术", "手术", 9000, 18000},
	{"膀胱取石手术", "手术", 3500, 7000},
	{"子宫蓄脓手术", "手术", 3000, 6500},
	{"绝育手术（公）", "手术", 800, 1800},
	{"绝育手术（母）", "手术", 1500, 3200},
	{"洁牙手术", "手术", 800, 2000},
	{"清创缝合", "手术", 600, 1800},
	{"异物取出手术", "手术", 3500, 7500},
	{"白内障手术", "手术", 6000, 12000},
	{"肿瘤切除", "手术", 4000, 9000},
	{"牙齿打磨", "手术", 380, 780},

	// 住院
	{"住院费（1 天）", "住院", 180, 460},
	{"ICU 监护费（1 天）", "住院", 500, 1200},
	{"隔离住院费（1 天）", "住院", 300, 700},
	{"吸氧费", "住院", 200, 600},

	// 疫苗
	{"犬四联疫苗", "疫苗", 120, 260},
	{"犬八联疫苗", "疫苗", 180, 360},
	{"狂犬疫苗", "疫苗", 100, 200},
	{"猫三联疫苗", "疫苗", 150, 320},
	{"猫狂犬疫苗", "疫苗", 100, 200},
	{"兔病毒性出血症疫苗", "疫苗", 80, 180},
	{"鸟类疫苗", "疫苗", 60, 160},

	// 护理
	{"药浴（1 次）", "护理", 120, 300},
	{"水疗康复（1 次）", "护理", 100, 260},
	{"康复理疗（1 次）", "护理", 150, 400},
	{"针灸治疗（1 次）", "护理", 200, 480},
	{"换药 / 清创护理", "护理", 60, 200},
	{"导尿 / 冲洗", "护理", 200, 600},
	{"灌肠", "护理", 150, 400},
	{"雾化治疗", "护理", 80, 220},

	// 其他
	{"处方粮", "其他", 200, 520},
	{"伊丽莎白圈", "其他", 40, 120},
	{"宠物芯片植入", "其他", 150, 350},
	{"急诊挂号费", "其他", 50, 150},
	{"专家会诊费", "其他", 200, 600},
	{"宠物运输 / 转诊", "其他", 100, 400},
}

// 医生池（含职称与专长，用于分配病例）
type doctorInfo struct {
	Name      string
	Title     string
	Specialty string
}

var doctorPool = []doctorInfo{
	{"李医生", "主任兽医师", "内科 / 消化"},
	{"王医生", "副主任兽医师", "猫科 / 传染病"},
	{"赵医生", "主治兽医师", "骨科 / 外科"},
	{"陈医生", "主治兽医师", "异宠 / 皮肤"},
	{"刘医生", "住院医师", "急诊 / 影像"},
	{"孙医生", "主任兽医师", "心脏 / 内分泌"},
	{"周医生", "副主任兽医师", "眼科 / 神经"},
	{"吴医生", "主治兽医师", "泌尿 / 生殖"},
	{"郑医生", "住院医师", "内科 / 护理"},
	{"冯医生", "主治兽医师", "肿瘤 / 软组织外科"},
	{"蒋医生", "住院医师", "皮肤 / 耳科"},
	{"韩医生", "副主任兽医师", "影像诊断"},
}

// 主人姓氏与名字
var ownerSurnames = []string{"张", "王", "李", "赵", "刘", "陈", "杨", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "林", "高", "罗", "郑", "梁", "谢", "宋", "唐", "许", "邓", "冯", "韩", "曹", "彭", "曾", "肖", "田", "董", "袁", "潘", "于", "蒋", "蔡", "余", "杜", "叶", "程", "苏", "魏", "吕", "丁", "任", "沈"}
var ownerGivenNames = []string{"先生", "女士", "小姐", "太太", "先生", "女士", "老板", "医生", "老师", "工程师"}

// 城市与地址
var cities = []struct {
	City      string
	Districts []string
}{
	{"北京市", []string{"朝阳区", "海淀区", "东城区", "西城区", "丰台区", "通州区", "昌平区"}},
	{"上海市", []string{"浦东新区", "徐汇区", "静安区", "黄浦区", "长宁区", "闵行区", "杨浦区"}},
	{"广州市", []string{"天河区", "越秀区", "海珠区", "白云区", "番禺区", "荔湾区"}},
	{"深圳市", []string{"南山区", "福田区", "罗湖区", "宝安区", "龙岗区", "龙华区"}},
	{"杭州市", []string{"西湖区", "拱墅区", "滨江区", "余杭区", "上城区"}},
	{"成都市", []string{"武侯区", "锦江区", "青羊区", "高新区", "金牛区"}},
	{"南京市", []string{"鼓楼区", "玄武区", "秦淮区", "建邺区", "江宁区"}},
	{"武汉市", []string{"武昌区", "洪山区", "江汉区", "汉阳区", "东湖高新区"}},
	{"西安市", []string{"雁塔区", "碑林区", "未央区", "高新区", "莲湖区"}},
	{"重庆市", []string{"渝中区", "江北区", "渝北区", "沙坪坝区", "南岸区"}},
}

var roadNames = []string{"人民路", "中山路", "建设大道", "解放路", "文化街", "长江路", "黄河大道", "科技路", "花园路", "幸福里", "光明路", "和平街", "望京西路", "世纪大道", "体育西路", "创业大街"}

// 过敏史池
var allergies = []string{"无", "无", "无", "无", "青霉素过敏", "磺胺类药物过敏", "头孢类过敏", "某种食物过敏（牛肉）", "花粉过敏", "尘螨过敏", "未知（首次就诊）"}

// GeneratePets 生成 count 只宠物的模拟数据。
// 固定 seed 保证结果可复现；skip 用于跳过已被「手工精选」的档案数量，
// 避免与 SeedPets 的主键冲突。
func GeneratePets(count int, seed int64) []*model.Pet {
	if count <= 0 {
		return nil
	}
	rng := rand.New(rand.NewSource(seed))

	speciesList := []string{
		model.SpeciesDog, model.SpeciesCat, model.SpeciesDog, model.SpeciesCat,
		model.SpeciesDog, model.SpeciesCat, model.SpeciesRabbit, model.SpeciesBird,
		model.SpeciesHamster, model.SpeciesReptile, model.SpeciesOther,
	}
	// 权重：犬猫占多数，贴合真实宠物医院构成
	weights := []int{20, 18, 14, 12, 10, 8, 6, 4, 3, 2, 3}
	total := 0
	for _, w := range weights {
		total += w
	}

	pets := make([]*model.Pet, 0, count)
	usedChip := map[string]bool{}

	for i := 0; i < count; i++ {
		// --- 选种类（加权） ---
		r := rng.Intn(total)
		acc := 0
		sp := speciesList[0]
		for j, w := range weights {
			acc += w
			if r < acc {
				sp = speciesList[j]
				break
			}
		}

		name := pick(rng, namePools[sp])
		breed := pick(rng, breedPools[sp])
		color := pick(rng, colorPools[sp])
		gender := pick(rng, []string{"公", "母"})

		// --- 年龄（不同种类寿命不同） ---
		var ageMonths int
		switch sp {
		case model.SpeciesDog:
			ageMonths = 2 + rng.Intn(180)
		case model.SpeciesCat:
			ageMonths = 2 + rng.Intn(200)
		case model.SpeciesRabbit:
			ageMonths = 2 + rng.Intn(96)
		case model.SpeciesBird:
			ageMonths = 2 + rng.Intn(180)
		case model.SpeciesHamster:
			ageMonths = 1 + rng.Intn(30)
		case model.SpeciesReptile:
			ageMonths = 3 + rng.Intn(240)
		default:
			ageMonths = 2 + rng.Intn(96)
		}

		// --- 主人信息 ---
		ownerName := pick(rng, ownerSurnames) + pick(rng, ownerGivenNames)
		// 生成不重复的电话，避免看起来像重复客户
		phone := fmt.Sprintf("1%d%09d", 3+rng.Intn(6), rng.Intn(1000000000))

		loc := cities[rng.Intn(len(cities))]
		addr := fmt.Sprintf("%s%s%s%d号", loc.City, pick(rng, loc.Districts), pick(rng, roadNames), 1+rng.Intn(300))

		// 芯片号：部分宠物没有
		chip := ""
		for attempt := 0; attempt < 8; attempt++ {
			c := fmt.Sprintf("CHIP-%06d", 10000+rng.Intn(899999))
			if !usedChip[c] {
				usedChip[c] = true
				chip = c
				break
			}
		}
		if rng.Intn(10) < 2 { // 20% 未植入芯片
			chip = ""
		}

		// --- 疾病（可能多次就诊）；按种类筛选适用疾病，避免不合常理的组合 ---
		d := pickDiseaseFor(rng, sp)
		doctor := pickDoctorFor(rng, d.Category)

		// 就诊次数：轻症 1 次，重症可能多次随访
		visits := 1
		switch {
		case d.Severity >= 3:
			visits = 1 + rng.Intn(4)
		case d.Severity == 2:
			visits = 1 + rng.Intn(3)
		default:
			visits = 1 + rng.Intn(2)
		}

		baseDate := time.Date(2024, time.Month(1+rng.Intn(12)), 1+rng.Intn(28), 9+rng.Intn(9), rng.Intn(60), 0, 0, time.UTC)

		// --- 基础体重 / 体温（按种类） ---
		weight := baseWeight(rng, sp, ageMonths)
		temp := baseTemp(rng, sp)

		records := make([]model.MedicalRecord, 0, visits)
		charges := make([]model.Treatment, 0, visits*3)

		chargeSeq := 0
		for v := 0; v < visits; v++ {
			visitDate := baseDate.AddDate(0, 0, v*(3+rng.Intn(21)))
			dateStr := visitDate.Format("2006-01-02")

			// 首次是主诊断，后续是复查 / 恢复期
			diag := d.Name
			symptom := pick(rng, d.Symptoms)
			treat := pick(rng, d.Treatment)
			followUp := "如症状加重请及时复诊"
			weightNow := weight + float64(rng.Intn(1000))/1000*2 - 1
			if weightNow < 0.02 {
				weightNow = 0.02
			}
			tempNow := temp + float64(rng.Intn(20))/10 - 1

			if v > 0 {
				switch rng.Intn(3) {
				case 0:
					diag = d.Name + "（复查）"
					symptom = "症状较上次明显减轻，精神食欲改善"
					treat = "继续原方案巩固治疗"
					followUp = "一周后电话回访"
				case 1:
					diag = d.Name + "（恢复期）"
					symptom = "基本恢复正常，偶有轻微不适"
					treat = "减量用药 + 饮食管理"
					followUp = "2 周后复查"
				default:
					diag = d.Name + "（随访）"
					symptom = "病情稳定，无明显异常"
					treat = "维持治疗 + 定期监测"
					followUp = "3 个月后复查"
				}
			}

			presc := make([]string, 0, 2)
			for _, p := range d.Prescription {
				if rng.Intn(10) < 7 {
					presc = append(presc, p)
				}
			}
			if len(presc) == 0 {
				presc = append(presc, d.Prescription[0])
			}

			// 本次费用 = 若干收费项之和
			nCharge := 2 + rng.Intn(4)
			if d.Severity >= 3 {
				nCharge = 3 + rng.Intn(4)
			}
			var visitCharge float64
			for c := 0; c < nCharge; c++ {
				ct := chargeForDisease(rng, d, v)
				amount := round2(ct.Min + rng.Float64()*(ct.Max-ct.Min))
				// 后续复查适当降低费用
				if v > 0 && (ct.Category == "检查" || ct.Category == "手术") {
					amount = round2(amount * (0.4 + rng.Float64()*0.3))
				}
				charges = append(charges, model.Treatment{
					ID:       fmt.Sprintf("CH-SEED-%06d-%02d", i+1, chargeSeq),
					Item:     ct.Item,
					Category: ct.Category,
					Amount:   amount,
					Doctor:   doctor,
					Date:     dateStr,
				})
				visitCharge += amount
				chargeSeq++
			}

			records = append(records, model.MedicalRecord{
				ID:           fmt.Sprintf("MR-SEED-%06d-%02d", i+1, v),
				VisitDate:    dateStr,
				Doctor:       doctor,
				Diagnosis:    diag,
				Symptoms:     symptom,
				Treatment:    treat,
				Prescription: presc,
				WeightKG:     round2(weightNow),
				Temperature:  round2(tempNow),
				FollowUp:     followUp,
				Charge:       round2(visitCharge),
				CreatedAt:    visitDate.Format(time.RFC3339),
			})
		}

		// --- 状态：依据疾病严重度与最后就诊时间推断 ---
		lastVisit := baseDate.AddDate(0, 0, (visits-1)*(3+rng.Intn(21)))
		status := inferStatus(rng, d.Severity, lastVisit)

		note := ""
		switch rng.Intn(12) {
		case 0:
			note = "客户对费用较为敏感，已沟通治疗方案"
		case 1:
			note = "需长期随访，已建立慢病档案"
		case 2:
			note = "建议绝育，主人仍在考虑"
		case 3:
			note = "宠物极度紧张，就诊需两人配合"
		case 4:
			note = "已购买宠物保险，可走理赔流程"
		}

		pets = append(pets, &model.Pet{
			Name:       name,
			Species:    sp,
			Breed:      breed,
			Gender:     gender,
			AgeMonths:  ageMonths,
			Color:      color,
			ChipNo:     chip,
			OwnerName:  ownerName,
			OwnerPhone: phone,
			OwnerAddr:  addr,
			Doctor:     doctor,
			Disease:    d.Name,
			Status:     status,
			Allergy:    pick(rng, allergies),
			Note:       note,
			Records:    records,
			Charges:    charges,
		})
	}
	return pets
}

// pick 从切片随机取一个元素。
func pick(rng *rand.Rand, list []string) string {
	if len(list) == 0 {
		return ""
	}
	return list[rng.Intn(len(list))]
}

// pickDoctorFor 根据疾病大类挑选合适的医生；找不到则随机。
func pickDoctorFor(rng *rand.Rand, category string) string {
	var candidates []string
	for _, d := range doctorPool {
		if specialtyMatches(d.Specialty, category) {
			candidates = append(candidates, d.Name)
		}
	}
	if len(candidates) == 0 {
		return doctorPool[rng.Intn(len(doctorPool))].Name
	}
	return candidates[rng.Intn(len(candidates))]
}

// specialtyMatches 判断医生专长是否覆盖该疾病大类。
func specialtyMatches(specialty, category string) bool {
	mapping := map[string][]string{
		"内科 / 消化":    {"消化系统", "内分泌", "寄生虫", "口腔"},
		"猫科 / 传染病":   {"传染病", "呼吸系统", "寄生虫"},
		"骨科 / 外科":    {"骨科", "外科"},
		"异宠 / 皮肤":    {"皮肤", "行为", "口腔", "骨科", "呼吸系统", "消化系统"},
		"急诊 / 影像":    {"急诊", "外科", "中毒"},
		"心脏 / 内分泌":   {"内分泌", "呼吸系统", "急诊"},
		"眼科 / 神经":    {"眼科", "神经"},
		"泌尿 / 生殖":    {"泌尿", "生殖", "外科"},
		"内科 / 护理":    {"消化系统", "泌尿", "内分泌"},
		"肿瘤 / 软组织外科": {"外科", "皮肤"},
		"皮肤 / 耳科":    {"皮肤", "口腔"},
		"影像诊断":       {"骨科", "呼吸系统", "泌尿"},
	}
	for _, c := range mapping[specialty] {
		if c == category {
			return true
		}
	}
	return false
}

// chargeForDisease 根据疾病与就诊次序挑选合理的收费项目。
func chargeForDisease(rng *rand.Rand, d diseaseTemplate, visitIdx int) chargeTemplate {
	// 按疾病大类偏好收费类别
	var prefer []string
	switch d.Category {
	case "骨科", "外科":
		prefer = []string{"手术", "检查", "住院", "药品", "护理", "其他"}
	case "传染病", "急诊":
		prefer = []string{"药品", "检查", "住院", "护理", "其他"}
	case "皮肤", "口腔", "眼科", "寄生虫":
		prefer = []string{"检查", "药品", "护理", "其他"}
	case "泌尿", "生殖":
		prefer = []string{"检查", "药品", "手术", "住院", "其他"}
	case "内分泌", "神经":
		prefer = []string{"检查", "药品", "其他"}
	case "呼吸系统", "消化系统":
		prefer = []string{"检查", "药品", "住院", "护理", "其他"}
	default:
		prefer = []string{"检查", "药品", "其他", "护理"}
	}

	// 首次就诊才可能做手术；复查多为检查与药品
	if visitIdx > 0 {
		prefer = []string{"检查", "药品", "护理", "其他"}
	}

	want := prefer[rng.Intn(len(prefer))]
	var pool []chargeTemplate
	for _, c := range chargePool {
		if c.Category == want {
			pool = append(pool, c)
		}
	}
	if len(pool) == 0 {
		pool = chargePool
	}
	return pool[rng.Intn(len(pool))]
}

// baseWeight 按种类与年龄估算体重（kg）。
func baseWeight(rng *rand.Rand, species string, ageMonths int) float64 {
	var base, jitter float64
	switch species {
	case model.SpeciesDog:
		base, jitter = 4+rng.Float64()*30, 0.5
	case model.SpeciesCat:
		base, jitter = 3+rng.Float64()*4, 0.3
	case model.SpeciesRabbit:
		base, jitter = 1.2+rng.Float64()*1.6, 0.15
	case model.SpeciesBird:
		base, jitter = 0.03+rng.Float64()*0.09, 0.01
	case model.SpeciesHamster:
		base, jitter = 0.03+rng.Float64()*0.06, 0.005
	case model.SpeciesReptile:
		base, jitter = 0.2+rng.Float64()*3.5, 0.2
	default:
		base, jitter = 0.5+rng.Float64()*1.5, 0.1
	}
	// 幼年体重偏轻
	if ageMonths < 6 {
		base *= 0.5
	} else if ageMonths < 12 {
		base *= 0.75
	}
	return round2(base + rng.Float64()*jitter)
}

// baseTemp 按种类给出正常体温范围（℃）。
func baseTemp(rng *rand.Rand, species string) float64 {
	var lo, hi float64
	switch species {
	case model.SpeciesDog, model.SpeciesCat:
		lo, hi = 38.0, 39.2
	case model.SpeciesRabbit:
		lo, hi = 38.3, 39.5
	case model.SpeciesBird:
		lo, hi = 40.0, 42.0
	case model.SpeciesReptile:
		lo, hi = 26.0, 32.0
	default:
		lo, hi = 36.5, 38.5
	}
	return round2(lo + rng.Float64()*(hi-lo))
}

// inferStatus 依据严重程度与最后就诊时间推断当前状态。
func inferStatus(rng *rand.Rand, severity int, lastVisit time.Time) string {
	daysSince := int(time.Since(lastVisit).Hours() / 24)
	if daysSince < 0 {
		daysSince = 0
	}
	// 近期就诊的重症更可能在住院 / 就诊中
	if daysSince <= 14 && severity >= 3 {
		switch rng.Intn(3) {
		case 0:
			return model.StatusHospitalized
		case 1:
			return model.StatusTreating
		default:
			return model.StatusChronic
		}
	}
	if daysSince <= 30 && severity == 2 {
		if rng.Intn(2) == 0 {
			return model.StatusTreating
		}
		return model.StatusRecovered
	}
	switch rng.Intn(10) {
	case 0:
		return model.StatusWaiting
	case 1, 2:
		return model.StatusChronic
	case 3:
		return model.StatusTreating
	default:
		return model.StatusRecovered
	}
}
