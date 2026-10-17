#include "shape.hpp"

namespace zoo::shapes {

void Circle::accept(ShapeVisitor& visitor) { visitor.visit(*this); }
void Square::accept(ShapeVisitor& visitor) { visitor.visit(*this); }
void Group::accept(ShapeVisitor& visitor) { visitor.visit(*this); }

double Group::area() const {
  double total = 0;
  for (const auto& child : children_) total += child->area();
  return total;
}

std::unique_ptr<Shape> Group::clone() const {
  auto copy = std::make_unique<Group>();
  for (const auto& child : children_) copy->add(child->clone());
  return copy;
}

std::unique_ptr<Shape> ShapeFactory::create(const std::string& kind, double size) const {
  if (kind == "circle") return std::make_unique<Circle>(size);
  return std::make_unique<Square>(size);
}

}  // namespace zoo::shapes
