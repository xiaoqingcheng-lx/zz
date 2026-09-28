package store

import (
	"path/filepath"
	"testing"

	"pethospital/internal/model"
)

func TestCompactPersistsRecords(t *testing.T) {
	path := filepath.Join(t.TempDir(), "pet.db")
	s, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	p, err := s.Create(&model.Pet{
		Name: "旺财", Species: model.SpeciesDog, OwnerName: "张三", OwnerPhone: "13800001111",
		Doctor: "李医生", Disease: "体检", Status: model.StatusWaiting,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.AddRecord(p.ID, model.MedicalRecord{Doctor: "李医生", Diagnosis: "健康", Charge: 80}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AddRecord(p.ID, model.MedicalRecord{Doctor: "", Diagnosis: "健康"}); err == nil {
		t.Fatal("AddRecord accepted an empty doctor")
	}
	if err := s.Compact(); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}

	s, err = Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	got, err := s.Get(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Records) != 1 || got.Records[0].Diagnosis != "健康" || got.Records[0].Charge != 80 {
		t.Fatalf("records after reopen = %#v", got.Records)
	}
}
