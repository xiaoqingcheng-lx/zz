package api

import (
	"os"

	"pethospital/internal/model"
)

// ---------------------------------------------------------------------------
// ANSI 终端着色（用于请求日志）
// ---------------------------------------------------------------------------

const (
	ansiReset  = "\x1b[0m"
	ansiDim    = "\x1b[2m"
	ansiRed    = "\x1b[31m"
	ansiYellow = "\x1b[33m"
	ansiGreen  = "\x1b[32m"
	ansiCyan   = "\x1b[36m"
)

// colorFor 根据 HTTP 状态码返回对应的 ANSI 颜色。
func colorFor(code int) string {
	switch {
	case code >= 500:
		return ansiRed
	case code >= 400:
		return ansiYellow
	case code >= 300:
		return ansiCyan
	default:
		return ansiGreen
	}
}

// dim 把文本渲染为暗色。
func dim(s string) string {
	if s == "" {
		return ""
	}
	return ansiDim + s + ansiReset
}

// statFile 返回文件大小（字节）。
func statFile(path string) (int64, error) {
	fi, err := os.Stat(path)
	if err != nil {
		return 0, err
	}
	return fi.Size(), nil
}

// ---------------------------------------------------------------------------
// 演示数据
// ---------------------------------------------------------------------------

// SeedPets 返回一组演示用的宠物档案，覆盖各种种类、状态与消费场景。
func SeedPets() []*model.Pet {
	return []*model.Pet{
		{
			Name: "旺财", Species: model.SpeciesDog, Breed: "金毛寻回犬", Gender: "公", AgeMonths: 36,
			Color: "金黄", ChipNo: "CHIP-90001",
			OwnerName: "张三", OwnerPhone: "13800001111", OwnerAddr: "北京市朝阳区望京西路 1 号",
			Doctor: "李医生", Disease: "急性肠胃炎", Status: model.StatusRecovered, Allergy: "青霉素过敏",
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-01-12", Doctor: "李医生", Diagnosis: "急性肠胃炎",
					Symptoms: "呕吐 3 次、腹泻、食欲不振", Treatment: "静脉补液 + 消炎",
					Prescription: []string{"阿莫西林克拉维酸钾", "蒙脱石散", "益生菌"},
					WeightKG:     28.4, Temperature: 39.2, FollowUp: "3 天后复查", Charge: 860,
				},
				{
					VisitDate: "2025-01-15", Doctor: "李医生", Diagnosis: "肠胃炎恢复期",
					Symptoms: "精神明显好转，仍轻微软便", Treatment: "口服药 + 处方粮",
					Prescription: []string{"益生菌"}, WeightKG: 28.1, Temperature: 38.6,
					FollowUp: "一周后电话回访", Charge: 320,
				},
			},
			Charges: []model.Treatment{
				{Item: "血常规检查", Category: "检查", Amount: 180, Doctor: "李医生", Date: "2025-01-12"},
				{Item: "静脉输液", Category: "药品", Amount: 420, Doctor: "李医生", Date: "2025-01-12"},
				{Item: "犬用益生菌", Category: "药品", Amount: 160, Doctor: "李医生", Date: "2025-01-12"},
				{Item: "复诊检查", Category: "检查", Amount: 100, Doctor: "李医生", Date: "2025-01-15"},
				{Item: "处方粮", Category: "其他", Amount: 320, Doctor: "李医生", Date: "2025-01-15"},
			},
		},
		{
			Name: "咪咪", Species: model.SpeciesCat, Breed: "英国短毛猫", Gender: "母", AgeMonths: 18,
			Color: "蓝灰", ChipNo: "CHIP-90002",
			OwnerName: "李四", OwnerPhone: "13900002222", OwnerAddr: "上海市浦东新区世纪大道 88 号",
			Doctor: "王医生", Disease: "猫瘟", Status: model.StatusHospitalized, Allergy: "无",
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-02-03", Doctor: "王医生", Diagnosis: "猫泛白细胞减少症（猫瘟）",
					Symptoms: "高热 40.5℃、精神沉郁、拒食、呕吐", Treatment: "隔离住院 + 抗病毒血清 + 补液",
					Prescription: []string{"猫瘟单抗", "干扰素", "葡萄糖注射液", "止吐针"},
					WeightKG:     4.1, Temperature: 40.5, FollowUp: "住院观察 5 天", Charge: 3200,
				},
			},
			Charges: []model.Treatment{
				{Item: "猫瘟抗原检测", Category: "检查", Amount: 260, Doctor: "王医生", Date: "2025-02-03"},
				{Item: "猫瘟单抗", Category: "药品", Amount: 1200, Doctor: "王医生", Date: "2025-02-03"},
				{Item: "住院费（5 天）", Category: "住院", Amount: 1500, Doctor: "王医生", Date: "2025-02-03"},
				{Item: "静脉输液", Category: "药品", Amount: 640, Doctor: "王医生", Date: "2025-02-04"},
			},
		},
		{
			Name: "豆豆", Species: model.SpeciesDog, Breed: "柯基", Gender: "公", AgeMonths: 60,
			Color: "三色", ChipNo: "CHIP-90003",
			OwnerName: "王五", OwnerPhone: "13700003333", OwnerAddr: "广州市天河区体育西路 5 号",
			Doctor: "赵医生", Disease: "股骨骨折", Status: model.StatusTreating, Allergy: "无",
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-03-08", Doctor: "赵医生", Diagnosis: "右后肢股骨中段骨折",
					Symptoms: "坠楼后右后肢无法着地、明显疼痛", Treatment: "内固定手术 + 术后制动",
					Prescription: []string{"美洛昔康", "头孢氨苄", "钙片"},
					WeightKG:     11.2, Temperature: 38.9, FollowUp: "术后 2 周拆线，1 个月复查 X 光", Charge: 6800,
				},
			},
			Charges: []model.Treatment{
				{Item: "X 光检查（两张）", Category: "检查", Amount: 400, Doctor: "赵医生", Date: "2025-03-08"},
				{Item: "骨折内固定手术", Category: "手术", Amount: 5200, Doctor: "赵医生", Date: "2025-03-08"},
				{Item: "麻醉费", Category: "手术", Amount: 800, Doctor: "赵医生", Date: "2025-03-08"},
				{Item: "术后消炎针", Category: "药品", Amount: 560, Doctor: "赵医生", Date: "2025-03-09"},
				{Item: "住院费（3 天）", Category: "住院", Amount: 900, Doctor: "赵医生", Date: "2025-03-09"},
			},
		},
		{
			Name: "雪球", Species: model.SpeciesRabbit, Breed: "垂耳兔", Gender: "母", AgeMonths: 12,
			Color: "白", OwnerName: "赵六", OwnerPhone: "13600004444",
			Doctor: "李医生", Disease: "牙科疾病（牙齿过长）", Status: model.StatusChronic,
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-03-20", Doctor: "李医生", Diagnosis: "臼齿过长导致进食困难",
					Symptoms: "流涎、体重下降、拒绝进食干草", Treatment: "牙齿打磨 + 饮食调整",
					Prescription: []string{"提摩西草", "维生素 C 补充剂"},
					WeightKG:     1.6, Temperature: 38.5, FollowUp: "每月定期磨牙", Charge: 780,
				},
			},
			Charges: []model.Treatment{
				{Item: "兔用麻醉", Category: "手术", Amount: 300, Doctor: "李医生", Date: "2025-03-20"},
				{Item: "牙齿打磨", Category: "手术", Amount: 480, Doctor: "李医生", Date: "2025-03-20"},
			},
		},
		{
			Name: "皮皮", Species: model.SpeciesBird, Breed: "玄凤鹦鹉", Gender: "公", AgeMonths: 24,
			Color: "黄灰", OwnerName: "孙七", OwnerPhone: "13500005555",
			Doctor: "陈医生", Disease: "羽毛啄癖", Status: model.StatusRecovered,
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-04-02", Doctor: "陈医生", Diagnosis: "营养性羽毛啄癖",
					Symptoms: "胸腹部羽毛大面积脱落", Treatment: "补充微量元素 + 环境丰容",
					Prescription: []string{"鸟类综合维生素", "墨鱼骨"},
					WeightKG:     0.09, Temperature: 41.0, FollowUp: "两周后复查", Charge: 260,
				},
			},
			Charges: []model.Treatment{
				{Item: "鸟类体检", Category: "检查", Amount: 120, Doctor: "陈医生", Date: "2025-04-02"},
				{Item: "鸟类综合维生素", Category: "药品", Amount: 140, Doctor: "陈医生", Date: "2025-04-02"},
			},
		},
		{
			Name: "团子", Species: model.SpeciesCat, Breed: "布偶猫", Gender: "母", AgeMonths: 8,
			Color: "海豹双色", ChipNo: "CHIP-90006",
			OwnerName: "周八", OwnerPhone: "13400006666",
			Doctor: "王医生", Disease: "猫鼻支", Status: model.StatusWaiting,
			Allergy: "无",
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-04-18", Doctor: "王医生", Diagnosis: "猫疱疹病毒引起的上呼吸道感染",
					Symptoms: "打喷嚏、眼鼻分泌物增多、结膜充血", Treatment: "抗病毒滴眼液 + 口服赖氨酸",
					Prescription: []string{"泛昔洛韦滴眼液", "L-赖氨酸"},
					WeightKG:     3.2, Temperature: 39.4, FollowUp: "5 天后复查", Charge: 520,
				},
			},
			Charges: []model.Treatment{
				{Item: "猫呼吸道五联检测", Category: "检查", Amount: 320, Doctor: "王医生", Date: "2025-04-18"},
				{Item: "泛昔洛韦滴眼液", Category: "药品", Amount: 120, Doctor: "王医生", Date: "2025-04-18"},
				{Item: "L-赖氨酸", Category: "药品", Amount: 80, Doctor: "王医生", Date: "2025-04-18"},
			},
		},
		{
			Name: "大金", Species: model.SpeciesDog, Breed: "拉布拉多", Gender: "公", AgeMonths: 48,
			Color: "奶白", ChipNo: "CHIP-90007",
			OwnerName: "吴九", OwnerPhone: "13300007777",
			Doctor: "赵医生", Disease: "髋关节发育不良", Status: model.StatusChronic,
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-05-06", Doctor: "赵医生", Diagnosis: "双侧髋关节发育不良（中期）",
					Symptoms: "起立困难、运动后跛行", Treatment: "关节保护药物 + 控制体重 + 水疗",
					Prescription: []string{"关节软骨素", "鱼油", "止痛药"},
					WeightKG:     34.5, Temperature: 38.7, FollowUp: "每 3 个月复查，必要时手术", Charge: 1650,
				},
			},
			Charges: []model.Treatment{
				{Item: "髋关节 X 光", Category: "检查", Amount: 450, Doctor: "赵医生", Date: "2025-05-06"},
				{Item: "关节软骨素（1 疗程）", Category: "药品", Amount: 800, Doctor: "赵医生", Date: "2025-05-06"},
				{Item: "水疗康复（4 次）", Category: "护理", Amount: 400, Doctor: "赵医生", Date: "2025-05-10"},
			},
		},
		{
			Name: "小白", Species: model.SpeciesHamster, Breed: "布丁仓鼠", Gender: "母", AgeMonths: 6,
			Color: "奶油", OwnerName: "郑十", OwnerPhone: "13200008888",
			Doctor: "陈医生", Disease: "湿尾症", Status: model.StatusRecovered,
			Records: []model.MedicalRecord{
				{
					VisitDate: "2025-05-22", Doctor: "陈医生", Diagnosis: "细菌性湿尾症",
					Symptoms: "尾部潮湿、精神萎靡、腹泻", Treatment: "口服抗生素 + 保温",
					Prescription: []string{"恩诺沙星滴剂"},
					WeightKG:     0.05, Temperature: 37.5, FollowUp: "3 天后复诊", Charge: 150,
				},
			},
			Charges: []model.Treatment{
				{Item: "仓鼠体检", Category: "检查", Amount: 80, Doctor: "陈医生", Date: "2025-05-22"},
				{Item: "恩诺沙星滴剂", Category: "药品", Amount: 70, Doctor: "陈医生", Date: "2025-05-22"},
			},
		},
	}
}
