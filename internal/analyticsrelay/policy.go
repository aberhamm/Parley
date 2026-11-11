// Package analyticsrelay is the bounded, identity-free transport to a private collector.
package analyticsrelay

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"strings"
)

//go:embed policy.generated.json
var policyBytes []byte

type finitePolicy struct {
	Schema           int                            `json:"schema"`
	Website          string                         `json:"website"`
	Hostname         string                         `json:"hostname"`
	Title            string                         `json:"title"`
	CollectorVersion string                         `json:"collector_version"`
	CollectorImage   string                         `json:"collector_image"`
	TrackerSHA256    string                         `json:"tracker_sha256"`
	Pages            []string                       `json:"pages"`
	Events           map[string]map[string][]string `json:"events"`
}

var policy = func() finitePolicy {
	var p finitePolicy
	if err := json.Unmarshal(policyBytes, &p); err != nil {
		panic("invalid embedded analytics policy")
	}
	return p
}()

func PolicySHA256() string { sum := sha256.Sum256(policyBytes); return hex.EncodeToString(sum[:]) }

// strictJSON rejects duplicate keys at every depth as well as trailing values.
// A struct decoder alone would silently accept the last duplicate selector.
func strictJSON(b []byte, out any) error {
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	if err := scanValue(d, 0); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return errors.New("trailing json")
	}
	if err := exactFields(b, reflect.TypeOf(out).Elem()); err != nil {
		return err
	}
	d = json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	return d.Decode(out)
}

// encoding/json matches struct tags case-insensitively. At this trust boundary,
// a differently spelled selector is unknown, even if the decoder recognizes it.
func exactFields(b []byte, typ reflect.Type) error {
	if typ.Kind() != reflect.Struct {
		return nil
	}
	var values map[string]json.RawMessage
	if err := json.NewDecoder(bytes.NewReader(b)).Decode(&values); err != nil {
		return err
	}
	fields := map[string]reflect.Type{}
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)
		name := strings.Split(field.Tag.Get("json"), ",")[0]
		fields[name] = field.Type
	}
	for key, value := range values {
		field, ok := fields[key]
		if !ok {
			return errors.New("unknown field")
		}
		if err := exactFields(value, field); err != nil {
			return err
		}
	}
	return nil
}

func scanValue(d *json.Decoder, depth int) error {
	if depth > 8 {
		return errors.New("json too deep")
	}
	tok, err := d.Token()
	if err != nil {
		return err
	}
	delim, ok := tok.(json.Delim)
	if !ok {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			k, e := d.Token()
			if e != nil {
				return e
			}
			key, ok := k.(string)
			if !ok || seen[key] {
				return errors.New("duplicate key")
			}
			seen[key] = true
			if e = scanValue(d, depth+1); e != nil {
				return e
			}
		}
	case '[':
		for d.More() {
			if e := scanValue(d, depth+1); e != nil {
				return e
			}
		}
	default:
		return errors.New("unexpected delimiter")
	}
	_, err = d.Token()
	return err
}

type envelope struct {
	Type    string  `json:"type"`
	Payload payload `json:"payload"`
}
type payload struct {
	Website  string          `json:"website"`
	Hostname string          `json:"hostname"`
	URL      string          `json:"url"`
	Title    string          `json:"title"`
	Referrer string          `json:"referrer"`
	Name     *string         `json:"name,omitempty"`
	Data     json.RawMessage `json:"data,omitempty"`
}

func project(b []byte) ([]byte, error) {
	var e envelope
	if err := strictJSON(b, &e); err != nil {
		return nil, err
	}
	// Require every fixed page field, including explicit empty referrer.
	var raw map[string]json.RawMessage
	json.Unmarshal(b, &raw)
	var fields map[string]json.RawMessage
	json.Unmarshal(raw["payload"], &fields)
	if e.Type != "event" || e.Payload.Website != policy.Website || e.Payload.Hostname != policy.Hostname || e.Payload.Title != policy.Title || e.Payload.Referrer != "" || len(fields["referrer"]) == 0 || string(fields["referrer"]) == "null" || !contains(policy.Pages, e.Payload.URL) {
		return nil, errors.New("invalid page")
	}
	p := payload{Website: policy.Website, Hostname: policy.Hostname, URL: e.Payload.URL, Title: policy.Title, Referrer: ""}
	if e.Payload.Name == nil {
		if len(e.Payload.Data) != 0 || fields["name"] != nil {
			return nil, errors.New("invalid page event")
		}
	} else {
		enums, ok := policy.Events[*e.Payload.Name]
		if !ok {
			return nil, errors.New("invalid event")
		}
		var data map[string]json.RawMessage
		if err := strictJSON(e.Payload.Data, &data); err != nil {
			return nil, err
		}
		if len(data) != len(enums)+1 || string(data["schema"]) != "1" {
			return nil, errors.New("invalid schema")
		}
		out := map[string]any{"schema": policy.Schema}
		for key, allowed := range enums {
			var value string
			if err := json.Unmarshal(data[key], &value); err != nil || !contains(allowed, value) {
				return nil, errors.New("invalid property")
			}
			out[key] = value
		}
		p.Name = e.Payload.Name
		p.Data, _ = json.Marshal(out)
	}
	return json.Marshal(envelope{Type: "event", Payload: p})
}
func contains(values []string, want string) bool {
	for _, v := range values {
		if v == want {
			return true
		}
	}
	return false
}
