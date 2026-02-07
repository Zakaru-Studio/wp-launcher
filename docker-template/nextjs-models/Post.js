const mongoose = require('mongoose')

const postSchema = new mongoose.Schema({
  title: {
    type: String,
    required: true,
    trim: true,
    maxlength: 200
  },
  content: {
    type: String,
    required: true
  },
  excerpt: {
    type: String,
    maxlength: 500
  },
  slug: {
    type: String,
    required: true,
    unique: true,
    lowercase: true
  },
  status: {
    type: String,
    enum: ['draft', 'published', 'archived'],
    default: 'draft'
  },
  author: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true
  },
  tags: [{
    type: String,
    trim: true,
    lowercase: true
  }],
  category: {
    type: String,
    trim: true,
    default: 'general'
  },
  featuredImage: {
    type: String,
    default: null
  },
  views: {
    type: Number,
    default: 0
  },
  publishedAt: {
    type: Date,
    default: null
  },
  seo: {
    title: {
      type: String,
      maxlength: 60
    },
    description: {
      type: String,
      maxlength: 160
    },
    keywords: [{
      type: String,
      trim: true
    }]
  }
}, {
  timestamps: true
})

// Index pour les recherches
postSchema.index({ slug: 1 })
postSchema.index({ status: 1, publishedAt: -1 })
postSchema.index({ author: 1 })
postSchema.index({ tags: 1 })
postSchema.index({ category: 1 })
postSchema.index({ title: 'text', content: 'text' })

// Générer l'excerpt automatiquement si non fourni
postSchema.pre('save', function(next) {
  if (!this.excerpt && this.content) {
    // Supprimer les balises HTML et prendre les 200 premiers caractères
    const textContent = this.content.replace(/<[^>]*>/g, '')
    this.excerpt = textContent.substring(0, 200) + (textContent.length > 200 ? '...' : '')
  }
  
  // Mettre à jour publishedAt si le statut change vers published
  if (this.status === 'published' && !this.publishedAt) {
    this.publishedAt = new Date()
  }
  
  next()
})

// Méthode pour générer un slug unique
postSchema.statics.generateUniqueSlug = async function(title, postId = null) {
  const baseSlug = title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
  
  let slug = baseSlug
  let counter = 1
  
  while (true) {
    const query = { slug }
    if (postId) {
      query._id = { $ne: postId }
    }
    
    const existingPost = await this.findOne(query)
    if (!existingPost) {
      return slug
    }
    
    slug = `${baseSlug}-${counter}`
    counter++
  }
}

// Méthode pour incrémenter les vues
postSchema.methods.incrementViews = function() {
  this.views += 1
  return this.save()
}

// Méthode pour obtenir les informations publiques du post
postSchema.methods.toPublicJSON = function() {
  return {
    id: this._id,
    title: this.title,
    content: this.content,
    excerpt: this.excerpt,
    slug: this.slug,
    status: this.status,
    author: this.author,
    tags: this.tags,
    category: this.category,
    featuredImage: this.featuredImage,
    views: this.views,
    publishedAt: this.publishedAt,
    createdAt: this.createdAt,
    updatedAt: this.updatedAt,
    seo: this.seo
  }
}

// Méthode statique pour obtenir les posts publiés
postSchema.statics.getPublishedPosts = function(options = {}) {
  const {
    page = 1,
    limit = 10,
    category = null,
    tags = null,
    author = null,
    search = null
  } = options
  
  const query = { status: 'published' }
  
  if (category) {
    query.category = category
  }
  
  if (tags && tags.length > 0) {
    query.tags = { $in: tags }
  }
  
  if (author) {
    query.author = author
  }
  
  if (search) {
    query.$text = { $search: search }
  }
  
  return this.find(query)
    .populate('author', 'firstName lastName avatar')
    .sort({ publishedAt: -1 })
    .skip((page - 1) * limit)
    .limit(limit)
}

module.exports = mongoose.model('Post', postSchema) 