#include "config.hpp"

namespace zoo {

std::string Config::get(const std::string& key) const {
  auto it = values_.find(key);
  return it == values_.end() ? std::string() : it->second;
}

}  // namespace zoo
