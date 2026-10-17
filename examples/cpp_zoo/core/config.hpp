#pragma once
#include <map>
#include <string>

namespace zoo {

/// Process-wide settings (Meyers singleton).
class Config {
 public:
  static Config& instance() {
    static Config instance;
    return instance;
  }
  Config(const Config&) = delete;
  Config& operator=(const Config&) = delete;

  std::string get(const std::string& key) const;
  void set(const std::string& key, const std::string& value) { values_[key] = value; }

 private:
  Config() = default;
  std::map<std::string, std::string> values_;
};

/// Plain data record.
struct Point {
  double x = 0;
  double y = 0;
};

}  // namespace zoo
