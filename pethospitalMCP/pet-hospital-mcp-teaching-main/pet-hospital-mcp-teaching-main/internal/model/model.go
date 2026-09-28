// Package model 定义宠物医院的核心数据模型。
//
// 说明：本项目刻意只依赖 Go 标准库，不引入任何第三方模块，
// 因此“单文件本地数据库”由 internal/store 自行实现：
// 一个 .db 文件 = 追加写日志 + 内存索引 + 自动压实(compaction)。
package model

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// 枚举 / 常量
// ---------------------------------------------------------------------------

// Species 宠物种类。
const (
	SpeciesDog     = "犬"
	SpeciesCat     = "猫"
	SpeciesRabbit  = "兔"
	SpeciesBird    = "鸟"
	SpeciesHamster = "仓鼠"
	SpeciesReptile = "爬宠"
	SpeciesOther   = "其他"
)

// Status 就诊状态。
const (
	StatusWaiting      = "待就诊"
	StatusTreating     = "就诊中"
	StatusHospitalized = "住院中"
	StatusRecovered    = "已康复"
	StatusChronic      = "慢性病随访"
)

// ValidSpecies 允许的宠物种类。
var ValidSpecies = []string{
	SpeciesDog, SpeciesCat, SpeciesRabbit, SpeciesBird,
	SpeciesHamster, SpeciesReptile, SpeciesOther,
}

// ValidStatus 允许的就诊状态。
var ValidStatus = []string{
	StatusWaiting, StatusTreating, StatusHospitalized,
	StatusRecovered, StatusChronic,
}

// ---------------------------------------------------------------------------
// 子结构
// ---------------------------------------------------------------------------

// Treatment 一次诊疗收费明细（累计即为“在医院总花费金额”）。
type Treatment struct {
	ID       string  `json:"id"`
	Item     string  `json:"item"`             // 收费项目，如「血常规检查」
	Category string  `json:"category"`         // 检查 / 药品 / 手术 / 住院 / 疫苗 / 其他
	Amount   float64 `json:"amount"`           // 金额（元）
	Doctor   string  `json:"doctor,omitempty"` // 经手医生
	Date     string  `json:"date"`             // 收费日期 YYYY-MM-DD
	Note     string  `json:"note,omitempty"`
}

// MedicalRecord 历史病历（一条就诊记录）。
type MedicalRecord struct {
	ID           string   `json:"id"`
	VisitDate    string   `json:"visitDate"`              // 就诊日期 YYYY-MM-DD
	Doctor       string   `json:"doctor"`                 // 医生姓名
	Diagnosis    string   `json:"diagnosis"`              // 诊断结论
	Symptoms     string   `json:"symptoms,omitempty"`     // 主诉 / 症状
	Treatment    string   `json:"treatment,omitempty"`    // 处置方案
	Prescription []string `json:"prescription,omitempty"` // 处方
	WeightKG     float64  `json:"weightKg,omitempty"`     // 就诊时体重
	Temperature  float64  `json:"temperature,omitempty"`  // 体温 ℃
	FollowUp     string   `json:"followUp,omitempty"`     // 复诊建议
	Charge       float64  `json:"charge"`                 // 本次费用
	CreatedAt    string   `json:"createdAt"`
}

// ---------------------------------------------------------------------------
// 主模型
// ---------------------------------------------------------------------------

// Pet 宠物（宠物医院的一号档案，聚合了病历与消费）。
type Pet struct {
	ID        string `json:"id"`
	Name      string `json:"name"`                // 宠物姓名
	Species   string `json:"species"`             // 种类：犬/猫/...
	Breed     string `json:"breed,omitempty"`     // 品种
	Gender    string `json:"gender,omitempty"`    // 公/母
	AgeMonths int    `json:"ageMonths,omitempty"` // 月龄
	Color     string `json:"color,omitempty"`     // 毛色
	ChipNo    string `json:"chipNo,omitempty"`    // 芯片号

	OwnerName  string `json:"ownerName"`           // 主人姓名
	OwnerPhone string `json:"ownerPhone"`          // 电话
	OwnerAddr  string `json:"ownerAddr,omitempty"` // 地址

	Doctor  string `json:"doctor"`            // 主治医生姓名
	Disease string `json:"disease"`           // 疾病 / 主要诊断
	Status  string `json:"status"`            // 就诊状态
	Allergy string `json:"allergy,omitempty"` // 过敏史
	Note    string `json:"note,omitempty"`    // 备注

	Records []MedicalRecord `json:"records"` // 历史病历
	Charges []Treatment     `json:"charges"` // 消费明细

	TotalCost  float64 `json:"totalCost"`  // 在医院总花费金额（自动汇总）
	VisitCount int     `json:"visitCount"` // 就诊次数（历史病历条数）

	CreatedAt string `json:"createdAt"`
	UpdatedAt string `json:"updatedAt"`
}

// TotalCost 说明：
// 该字段是由 Charges 自动汇总得到的派生值，客户端传值会被忽略。
// 见 Recalc()。

// ---------------------------------------------------------------------------
// 方法
// ---------------------------------------------------------------------------

// Recalc 重新计算派生字段：总花费、就诊次数、最后更新时间。
func (p *Pet) Recalc() {
	var sum float64
	for _, c := range p.Charges {
		sum += c.Amount
	}
	// 四舍五入到分，避免浮点误差累积。
	p.TotalCost = round2(sum)
	p.VisitCount = len(p.Records)
	p.UpdatedAt = nowString()
}

// MedicalHistory 以文本形式返回历史病历摘要（用于全文检索与导出）。
func (p *Pet) MedicalHistory() string {
	if len(p.Records) == 0 {
		return ""
	}
	var b strings.Builder
	for i, r := range p.Records {
		if i > 0 {
			b.WriteString(" | ")
		}
		fmt.Fprintf(&b, "%s %s %s %s", r.VisitDate, r.Doctor, r.Diagnosis, r.Treatment)
		if len(r.Prescription) > 0 {
			b.WriteString(" 处方:" + strings.Join(r.Prescription, "、"))
		}
	}
	return strings.TrimSpace(b.String())
}

// Validate 校验必填字段与枚举字段。新增时调用。
func (p *Pet) Validate() error {
	var errs []string
	if strings.TrimSpace(p.Name) == "" {
		errs = append(errs, "name(宠物姓名) 不能为空")
	}
	if strings.TrimSpace(p.OwnerName) == "" {
		errs = append(errs, "ownerName(主人姓名) 不能为空")
	}
	if err := ValidatePhone(p.OwnerPhone); err != nil {
		errs = append(errs, err.Error())
	}
	if strings.TrimSpace(p.Disease) == "" {
		errs = append(errs, "disease(疾病) 不能为空")
	}
	if strings.TrimSpace(p.Doctor) == "" {
		errs = append(errs, "doctor(医生姓名) 不能为空")
	}
	if p.Species == "" {
		p.Species = SpeciesOther
	} else if !contains(ValidSpecies, p.Species) {
		errs = append(errs, fmt.Sprintf("species 必须是 %s 之一", strings.Join(ValidSpecies, "/")))
	}
	if p.Status == "" {
		p.Status = StatusWaiting
	} else if !contains(ValidStatus, p.Status) {
		errs = append(errs, fmt.Sprintf("status 必须是 %s 之一", strings.Join(ValidStatus, "/")))
	}
	if p.AgeMonths < 0 {
		errs = append(errs, "ageMonths 不能为负数")
	}
	for i, c := range p.Charges {
		if c.Amount < 0 {
			errs = append(errs, fmt.Sprintf("charges[%d].amount 不能为负数", i))
		}
		if strings.TrimSpace(c.Item) == "" {
			errs = append(errs, fmt.Sprintf("charges[%d].item 不能为空", i))
		}
	}
	for i, r := range p.Records {
		if strings.TrimSpace(r.Diagnosis) == "" {
			errs = append(errs, fmt.Sprintf("records[%d].diagnosis 不能为空", i))
		}
		if strings.TrimSpace(r.Doctor) == "" {
			errs = append(errs, fmt.Sprintf("records[%d].doctor 不能为空", i))
		}
	}
	if len(errs) > 0 {
		return errors.New(strings.Join(errs, "; "))
	}
	return nil
}

// ValidatePhone 校验电话号码（中国大陆手机号或座机，允许带 +86 / 短横线）。
func ValidatePhone(phone string) error {
	s := strings.TrimSpace(phone)
	if s == "" {
		return errors.New("ownerPhone(电话) 不能为空")
	}
	digits := 0
	for _, r := range s {
		switch {
		case r >= '0' && r <= '9':
			digits++
		case r == '-' || r == '+' || r == ' ' || r == '(' || r == ')':
			// 允许的分隔符
		default:
			return fmt.Errorf("ownerPhone(电话) 含非法字符 %q", string(r))
		}
	}
	if digits < 7 || digits > 15 {
		return fmt.Errorf("ownerPhone(电话) 位数不合法(需 7-15 位数字): %s", s)
	}
	return nil
}

// ---------------------------------------------------------------------------
// 辅助
// ---------------------------------------------------------------------------

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}

func nowString() string {
	return time.Now().Format(time.RFC3339)
}

// NowString 暴露当前时间字符串。
func NowString() string { return nowString() }
